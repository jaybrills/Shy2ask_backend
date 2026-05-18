import firebase_admin.auth
from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema, extend_schema_field
from rest_framework import permissions, serializers, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.generics import GenericAPIView, ListAPIView, RetrieveUpdateAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from chat.models import ShyRequest

from .alias_utils import normalize_alias_name
from .models import ActiveUser, PendingVerificationUser, User
from .permissions import IsVerified
from .services import (
    create_and_send_reset_otp,
    create_and_send_verification_otp,
    verify_email_otp,
    verify_otp_and_reset_password,
)
from .validators import validate_disposable_email


class BearerTokenAuthentication(TokenAuthentication):
    keyword = "Bearer"


# ── Serializers ───────────────────────────────────────────────────────────────

class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField(write_only=True)
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)
    alias_name = serializers.CharField(required=False, allow_blank=True)
    phone_number = serializers.CharField(required=False, allow_blank=True)


class LoginSerializer(serializers.Serializer):
    email = serializers.EmailField()
    password = serializers.CharField()


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField()


class AliasAvailabilitySerializer(serializers.Serializer):
    alias_name = serializers.CharField()
    first_name = serializers.CharField(required=False, allow_blank=True)
    last_name = serializers.CharField(required=False, allow_blank=True)


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField()


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField()
    new_password = serializers.CharField()


class FirebaseLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField(
        write_only=True,
        help_text="Firebase ID token obtained from the Google, Apple, or Phone sign-in SDK.",
    )


class VerifyPhoneSerializer(serializers.Serializer):
    firebase_token = serializers.CharField(
        help_text="Firebase ID token obtained after completing phone OTP verification in the app.",
    )


class CompletePhoneRegistrationSerializer(serializers.Serializer):
    firebase_token = serializers.CharField(
        help_text="The Firebase phone ID token from the initial firebase-login step.",
    )
    email = serializers.EmailField()
    first_name = serializers.CharField(required=False, allow_blank=True, default="")
    last_name = serializers.CharField(required=False, allow_blank=True, default="")


class ProfileSerializer(serializers.ModelSerializer):
    profile_picture = serializers.SerializerMethodField()
    is_verified = serializers.SerializerMethodField()

    class Meta:
        model = User
        fields = [
            "id",
            "email",
            "first_name",
            "last_name",
            "alias_name",
            "phone_number",
            "profile_picture",
            "is_email_verified",
            "is_phone_verified",
            "is_verified",
            "date_joined",
            "updated_at",
        ]
        read_only_fields = [
            "id", "email", "is_email_verified", "is_phone_verified",
            "is_verified", "date_joined", "updated_at", "profile_picture",
        ]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_profile_picture(self, obj):
        return obj.profile_picture.url if obj.profile_picture else None

    @extend_schema_field(serializers.BooleanField())
    def get_is_verified(self, obj):
        return obj.is_verified


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "alias_name", "profile_picture"]
        # phone_number is intentionally excluded — use POST /api/auth/verify-phone instead.
        # Allowing direct edits would bypass Firebase phone verification.


class DeviceRegisterSerializer(serializers.Serializer):
    fcm_token = serializers.CharField(max_length=4096)
    device_type = serializers.ChoiceField(
        choices=["android", "ios", "web"],
        default="android",
    )
    device_name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class DeviceUnregisterSerializer(serializers.Serializer):
    fcm_token = serializers.CharField(max_length=4096)


class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "alias_name", "is_active", "date_joined"]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _verification_user_payload(user: User) -> dict:
    """Consistent user payload included in every auth response."""
    return {
        "id": user.id,
        "email": user.email,
        "first_name": user.first_name,
        "last_name": user.last_name,
        "alias_name": user.alias_name,
        "phone_number": user.phone_number,
        "is_email_verified": user.is_email_verified,
        "is_phone_verified": user.is_phone_verified,
        "is_verified": user.is_verified,
    }


# ── Auth views ────────────────────────────────────────────────────────────────

class RegisterView(GenericAPIView):
    serializer_class = RegisterSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        try:
            validate_disposable_email(data["email"])
        except ValidationError as exc:
            return Response({"detail": str(exc.message)}, status=status.HTTP_400_BAD_REQUEST)

        existing = User.objects.find_by_email(data["email"])
        if existing:
            if not existing.is_email_verified:
                pending_user = PendingVerificationUser.objects.get(pk=existing.pk)
                create_and_send_verification_otp(pending_user)
                token, _ = Token.objects.get_or_create(user=pending_user)
                return Response(
                    {
                        **_verification_user_payload(pending_user),
                        "token": token.key,
                        "message": "Verification OTP resent. Please verify your email.",
                    },
                    status=status.HTTP_201_CREATED,
                )
            return Response(
                {"detail": "A user with this email already exists."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            user = User.objects.create_user(
                email=data["email"],
                password=data["password"],
                first_name=data.get("first_name", ""),
                last_name=data.get("last_name", ""),
                alias_name=data.get("alias_name", ""),
                phone_number=data.get("phone_number", ""),
            )
        except ValidationError as exc:
            return Response(
                {"detail": getattr(exc, "message_dict", exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        create_and_send_verification_otp(user)
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                **_verification_user_payload(user),
                "token": token.key,
                "message": "Please verify your email with the OTP sent to your inbox.",
            },
            status=status.HTTP_201_CREATED,
        )


class LoginView(GenericAPIView):
    serializer_class = LoginSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        user = authenticate(
            request,
            username=User.objects.normalize_email(serializer.validated_data["email"]).lower(),
            password=serializer.validated_data["password"],
        )
        if user is None or not user.is_active:
            return Response(
                {"detail": "Invalid email or password."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        token, _ = Token.objects.get_or_create(user=user)
        return Response({"token": token.key, "user": _verification_user_payload(user)})


class ForgotPasswordView(GenericAPIView):
    serializer_class = EmailSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        create_and_send_reset_otp(serializer.validated_data["email"])
        return Response({"message": "If an account exists for this email, a reset code has been sent."})


class ResetPasswordView(GenericAPIView):
    serializer_class = ResetPasswordSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        if len(data["new_password"]) < 8:
            return Response(
                {"detail": "Password must be at least 8 characters."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        if not verify_otp_and_reset_password(data["email"], data["otp"], data["new_password"]):
            return Response(
                {"detail": "Invalid or expired OTP. Request a new code."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user = User.objects.find_by_email(data["email"])
        if user:
            from account.push_notifications import N
            from account.tasks import send_push_notification_task
            title, body = N.PASSWORD_CHANGED.render()
            send_push_notification_task.delay(
                user_id=user.id,
                title=title,
                body=body,
                data={"type": N.PASSWORD_CHANGED.key, "priority": N.PASSWORD_CHANGED.priority.value},
            )

        return Response({"message": "Password has been reset. You can now log in."})


class VerifyEmailView(GenericAPIView):
    serializer_class = VerifyEmailSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        try:
            validate_disposable_email(data["email"])
        except ValidationError as exc:
            return Response({"detail": str(exc.message)}, status=status.HTTP_400_BAD_REQUEST)

        user = verify_email_otp(data["email"], data["otp_code"])
        if not user:
            return Response(
                {"detail": "Invalid or expired OTP code. Request a new one via resend-verification."},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response({
            "message": "Email verified successfully.",
            "user": _verification_user_payload(user),
        })


class ResendVerificationView(GenericAPIView):
    serializer_class = EmailSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        try:
            validate_disposable_email(email)
        except ValidationError as exc:
            return Response({"detail": str(exc.message)}, status=status.HTTP_400_BAD_REQUEST)

        user = PendingVerificationUser.objects.find_by_email(email)
        if not user:
            return Response({"message": "If an account exists for this email, a verification code has been sent."})
        if user.is_email_verified:
            return Response({"detail": "Email is already verified."}, status=status.HTTP_400_BAD_REQUEST)
        create_and_send_verification_otp(user)
        return Response({"message": "Verification code sent. Check your email."})


class FirebaseLoginView(GenericAPIView):
    """
    Authenticate via a Firebase ID token (Google, Apple, or Phone Sign-In).

    Google / Apple:
      Always returns a token + user. is_new_user=true on first login.
      is_email_verified will be True; is_phone_verified may be False — frontend
      should prompt phone verification if so.

    Phone (new user):
      Returns { is_new_user: true, phone_number } with NO token.
      Frontend must collect email/name and call POST /api/auth/complete-phone-registration.

    Phone (existing user):
      Returns token + user as normal.
    """

    serializer_class = FirebaseLoginSerializer
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        request=FirebaseLoginSerializer,
        summary="Login or register via Firebase (Google / Apple / Phone)",
    )
    def post(self, request):
        from account.firebase_auth_service import get_firebase_login_result, verify_firebase_token

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            decoded = verify_firebase_token(serializer.validated_data["id_token"])
        except firebase_admin.auth.RevokedIdTokenError:
            return Response(
                {"detail": "Token has been revoked. Please sign in again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except firebase_admin.auth.ExpiredIdTokenError:
            return Response(
                {"detail": "Token has expired. Please sign in again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except firebase_admin.auth.InvalidIdTokenError:
            return Response({"detail": "Invalid token."}, status=status.HTTP_401_UNAUTHORIZED)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        try:
            user, is_new_user = get_firebase_login_result(decoded)
        except ValueError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_400_BAD_REQUEST)
        except PermissionError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_403_FORBIDDEN)
        except ValidationError as exc:
            return Response(
                {"detail": getattr(exc, "message_dict", exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # New phone user — no account yet, redirect to registration
        if user is None:
            return Response({
                "is_new_user": True,
                "phone_number": decoded.get("phone_number", ""),
            }, status=status.HTTP_200_OK)

        token, _ = Token.objects.get_or_create(user=user)
        return Response({
            "token": token.key,
            "is_new_user": is_new_user,
            "user": _verification_user_payload(user),
        })


class CompletePhoneRegistrationView(GenericAPIView):
    """
    Second step for phone-first registrations.

    The frontend re-sends the same Firebase phone token (proves the phone is still
    authenticated), plus the user's email and name. We create the account,
    mark phone as verified, and send an email OTP.
    """

    serializer_class = CompletePhoneRegistrationSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        from account.firebase_auth_service import verify_firebase_token

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data

        # Re-verify the Firebase phone token
        try:
            decoded = verify_firebase_token(data["firebase_token"])
        except firebase_admin.auth.RevokedIdTokenError:
            return Response(
                {"detail": "Token has been revoked. Please sign in again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except firebase_admin.auth.ExpiredIdTokenError:
            return Response(
                {"detail": "Token has expired. Please sign in with your phone again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except firebase_admin.auth.InvalidIdTokenError:
            return Response({"detail": "Invalid token."}, status=status.HTTP_401_UNAUTHORIZED)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        sign_in_provider = decoded.get("firebase", {}).get("sign_in_provider", "")
        if sign_in_provider != "phone":
            return Response(
                {"detail": "This endpoint only accepts phone authentication tokens."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        phone_number: str = decoded.get("phone_number", "")
        uid: str = decoded["uid"]
        email: str = data["email"]

        try:
            validate_disposable_email(email)
        except ValidationError as exc:
            return Response({"detail": str(exc.message)}, status=status.HTTP_400_BAD_REQUEST)

        # Guard: email already registered
        if User.objects.find_by_email(email):
            return Response(
                {"detail": "An account with this email already exists. Please log in instead."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        # Guard: phone already registered (race condition / retry)
        if User.objects.filter(phone_number=phone_number).exists():
            return Response(
                {"detail": "This phone number is already linked to an account. Please log in."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        from django.db import transaction
        from .models import SocialAccount

        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=email,
                    password=None,
                    first_name=data.get("first_name", ""),
                    last_name=data.get("last_name", ""),
                    phone_number=phone_number,
                )
                user.set_unusable_password()
                user.is_phone_verified = True
                user.save(update_fields=["is_phone_verified", "updated_at"])

                SocialAccount.objects.create(
                    user=user,
                    provider=SocialAccount.PROVIDER_PHONE,
                    provider_uid=uid,
                    email="",
                )
        except ValidationError as exc:
            return Response(
                {"detail": getattr(exc, "message_dict", exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        create_and_send_verification_otp(user)
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                **_verification_user_payload(user),
                "token": token.key,
                "message": "Account created. Please verify your email with the OTP sent to your inbox.",
            },
            status=status.HTTP_201_CREATED,
        )


class VerifyPhoneView(GenericAPIView):
    """
    Verify a phone number for an already-authenticated user.

    Called after the user completes Firebase phone OTP verification in the app.
    Works for:
      - Email/password users who need to add phone verification.
      - Google/Apple users who need to add phone verification.
    """

    serializer_class = VerifyPhoneSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        from account.firebase_auth_service import verify_firebase_token
        from .models import SocialAccount

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            decoded = verify_firebase_token(serializer.validated_data["firebase_token"])
        except firebase_admin.auth.RevokedIdTokenError:
            return Response(
                {"detail": "Token has been revoked. Please sign in again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except firebase_admin.auth.ExpiredIdTokenError:
            return Response(
                {"detail": "Token has expired. Please complete phone verification again."},
                status=status.HTTP_401_UNAUTHORIZED,
            )
        except firebase_admin.auth.InvalidIdTokenError:
            return Response({"detail": "Invalid token."}, status=status.HTTP_401_UNAUTHORIZED)
        except RuntimeError as exc:
            return Response({"detail": str(exc)}, status=status.HTTP_503_SERVICE_UNAVAILABLE)

        sign_in_provider = decoded.get("firebase", {}).get("sign_in_provider", "")
        if sign_in_provider != "phone":
            return Response(
                {"detail": "This endpoint only accepts phone authentication tokens."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        phone_number: str = decoded.get("phone_number", "")
        uid: str = decoded["uid"]
        user = request.user

        # Guard: phone already linked to a DIFFERENT account
        conflicting = (
            User.objects
            .filter(phone_number=phone_number)
            .exclude(pk=user.pk)
            .first()
        )
        if conflicting:
            return Response(
                {"detail": "This phone number is already linked to another account."},
                status=status.HTTP_409_CONFLICT,
            )

        from django.db import transaction
        with transaction.atomic():
            user.phone_number = phone_number
            user.is_phone_verified = True
            user.save(update_fields=["phone_number", "is_phone_verified", "updated_at"])

            SocialAccount.objects.update_or_create(
                provider=SocialAccount.PROVIDER_PHONE,
                provider_uid=uid,
                defaults={"user": user, "email": ""},
            )

        return Response({
            "message": "Phone number verified successfully.",
            "user": _verification_user_payload(user),
        })


# ── Profile ───────────────────────────────────────────────────────────────────

class CheckEmailView(GenericAPIView):
    serializer_class = EmailSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]
        try:
            validate_disposable_email(email)
        except ValidationError as exc:
            return Response({"is_available": False, "message": str(exc.message)})

        if User.objects.by_email(email).exists():
            return Response({"is_available": False, "message": "This email is already registered."})
        return Response({"is_available": True, "message": "Email is available."})


class CheckAliasView(GenericAPIView):
    serializer_class = AliasAvailabilitySerializer
    permission_classes = [permissions.AllowAny]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        current_user = request.user if getattr(request.user, "is_authenticated", False) else None
        first_name = serializer.validated_data.get("first_name")
        last_name = serializer.validated_data.get("last_name")

        if current_user:
            if first_name is None:
                first_name = current_user.first_name
            if last_name is None:
                last_name = current_user.last_name

        exclude_pk = current_user.pk if current_user else None
        is_available, message = User.get_alias_availability(
            serializer.validated_data["alias_name"],
            first_name=first_name or "",
            last_name=last_name or "",
            exclude_pk=exclude_pk,
        )

        suggestions = []
        if not is_available:
            suggestions = User.alias_suggestions(
                first_name=first_name or "",
                last_name=last_name or "",
                exclude_pk=exclude_pk,
            )

        response = {
            "is_available": is_available,
            "alias_name": normalize_alias_name(serializer.validated_data["alias_name"]),
            "message": str(message),
        }
        if not is_available:
            response["suggestions"] = suggestions
        return Response(response)


class UserNameByEmailView(GenericAPIView):
    serializer_class = EmailSerializer
    permission_classes = [permissions.AllowAny]

    def post(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        email = serializer.validated_data["email"]

        try:
            validate_disposable_email(email)
        except ValidationError as exc:
            return Response({"detail": str(exc.message)}, status=status.HTTP_400_BAD_REQUEST)

        user = User.objects.find_by_email(email)
        if user:
            return Response({"first_name": user.first_name, "last_name": user.last_name})

        first_request = (
            ShyRequest.objects.filter(target_email__iexact=email)
            .exclude(target_name="")
            .order_by("created_at")
            .first()
        )
        if first_request:
            return Response({"first_name": first_request.target_name, "last_name": None})

        return Response({"first_name": None, "last_name": None})


class ProfileMeView(RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [IsVerified]
    authentication_classes = [BearerTokenAuthentication]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method.lower() == "patch":
            return ProfileUpdateSerializer
        return ProfileSerializer

    def patch(self, request, *args, **kwargs):
        user = self.get_object()
        old_alias = user.alias_name
        old_phone = user.phone_number
        old_first = user.first_name
        old_last = user.last_name

        serializer = self.get_serializer(user, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except ValidationError as exc:
            return Response(
                {"detail": getattr(exc, "message_dict", exc.messages)},
                status=status.HTTP_400_BAD_REQUEST,
            )

        user.refresh_from_db()
        self._fire_profile_change_notifications(
            user=user,
            old_alias=old_alias,
            old_phone=old_phone,
            old_first=old_first,
            old_last=old_last,
        )

        return Response(ProfileSerializer(user).data)

    def _fire_profile_change_notifications(self, *, user, old_alias, old_phone, old_first, old_last):
        from account.push_notifications import N
        from account.tasks import send_push_notification_task

        if user.alias_name != old_alias:
            title, body = N.ALIAS_NAME_CHANGED.render(alias_name=user.alias_name)
            send_push_notification_task.delay(
                user_id=user.id,
                title=title,
                body=body,
                data={"type": N.ALIAS_NAME_CHANGED.key, "priority": N.ALIAS_NAME_CHANGED.priority.value},
            )

        if user.phone_number != old_phone:
            title, body = N.PHONE_NUMBER_CHANGED.render()
            send_push_notification_task.delay(
                user_id=user.id,
                title=title,
                body=body,
                data={"type": N.PHONE_NUMBER_CHANGED.key, "priority": N.PHONE_NUMBER_CHANGED.priority.value},
            )

        if user.first_name != old_first or user.last_name != old_last:
            title, body = N.FULL_NAME_CHANGED.render()
            send_push_notification_task.delay(
                user_id=user.id,
                title=title,
                body=body,
                data={"type": N.FULL_NAME_CHANGED.key, "priority": N.FULL_NAME_CHANGED.priority.value},
            )


class DeviceRegisterView(GenericAPIView):
    """
    Register (or re-register) a device for push notifications.
    Requires IsAuthenticated (not IsVerified) so users can register devices
    during the verification flow and receive OTP notifications.
    """

    serializer_class = DeviceRegisterSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        from account.models import UserDevice
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        UserDevice.objects.register(
            user=request.user,
            fcm_token=serializer.validated_data["fcm_token"],
            device_type=serializer.validated_data["device_type"],
            device_name=serializer.validated_data.get("device_name", ""),
        )
        return Response({"detail": "Device registered."}, status=status.HTTP_200_OK)


class DeviceUnregisterView(GenericAPIView):
    """Unregister a device. Call this on logout."""

    serializer_class = DeviceUnregisterSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def post(self, request):
        from account.models import UserDevice
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        UserDevice.objects.filter(
            user=request.user,
            fcm_token=serializer.validated_data["fcm_token"],
        ).update(is_active=False)
        return Response({"detail": "Device unregistered."}, status=status.HTTP_200_OK)


class UserListView(ListAPIView):
    serializer_class = UserListSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]

    def get_queryset(self):
        user = self.request.user
        if not getattr(user, "is_staff", False):
            return User.objects.none()
        qs = ActiveUser.objects.for_directory()
        search = self.request.query_params.get("search")
        return qs.search(search)

    def list(self, request, *args, **kwargs):
        if not getattr(request.user, "is_staff", False):
            return Response({"detail": "Staff only."}, status=status.HTTP_403_FORBIDDEN)
        queryset = self.get_queryset()
        limit = int(request.query_params.get("limit", 20))
        offset = int(request.query_params.get("offset", 0))
        items = queryset[offset: offset + limit]
        return Response(
            {
                "count": queryset.count(),
                "limit": limit,
                "offset": offset,
                "items": self.get_serializer(items, many=True).data,
            }
        )
