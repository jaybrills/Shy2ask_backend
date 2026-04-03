from django.contrib.auth import authenticate
from django.core.exceptions import ValidationError
from drf_spectacular.utils import extend_schema_field
from rest_framework import permissions, serializers, status
from rest_framework.authentication import TokenAuthentication
from rest_framework.authtoken.models import Token
from rest_framework.generics import GenericAPIView, ListAPIView, RetrieveUpdateAPIView
from rest_framework.parsers import FormParser, JSONParser, MultiPartParser
from rest_framework.response import Response

from .models import ActiveUser, PendingVerificationUser, User
from .services import (
    create_and_send_reset_otp,
    create_and_send_verification_otp,
    verify_email_otp,
    verify_otp_and_reset_password,
)
from .validators import validate_disposable_email


class BearerTokenAuthentication(TokenAuthentication):
    keyword = "Bearer"


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


class VerifyEmailSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp_code = serializers.CharField()


class ResetPasswordSerializer(serializers.Serializer):
    email = serializers.EmailField()
    otp = serializers.CharField()
    new_password = serializers.CharField()


class ProfileSerializer(serializers.ModelSerializer):
    profile_picture = serializers.SerializerMethodField()

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
            "is_verified",
            "date_joined",
            "updated_at",
        ]
        read_only_fields = ["id", "email", "is_verified", "date_joined", "updated_at", "profile_picture"]

    @extend_schema_field(serializers.CharField(allow_null=True))
    def get_profile_picture(self, obj):
        return obj.profile_picture.url if obj.profile_picture else None


class ProfileUpdateSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "alias_name", "phone_number", "profile_picture"]


class UserListSerializer(serializers.ModelSerializer):
    class Meta:
        model = User
        fields = ["id", "email", "first_name", "last_name", "alias_name", "is_active", "date_joined"]


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
            if not existing.is_verified:
                pending_user = PendingVerificationUser.objects.get(pk=existing.pk)
                create_and_send_verification_otp(pending_user)
                token, _ = Token.objects.get_or_create(user=pending_user)
                return Response(
                    {
                        "id": pending_user.id,
                        "email": pending_user.email,
                        "first_name": pending_user.first_name,
                        "last_name": pending_user.last_name,
                        "alias_name": pending_user.alias_name,
                        "phone_number": pending_user.phone_number,
                        "is_verified": False,
                        "token": token.key,
                        "message": "Verification OTP resent. Please verify your email.",
                    },
                    status=status.HTTP_201_CREATED,
                )
            return Response({"detail": "A user with this email already exists."}, status=status.HTTP_400_BAD_REQUEST)

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
            return Response({"detail": getattr(exc, "message_dict", exc.messages)}, status=status.HTTP_400_BAD_REQUEST)

        user.is_verified = False
        user.save(update_fields=["is_verified"])
        create_and_send_verification_otp(user)
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "id": user.id,
                "email": user.email,
                "first_name": user.first_name,
                "last_name": user.last_name,
                "alias_name": user.alias_name,
                "phone_number": user.phone_number,
                "is_verified": False,
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
            return Response({"detail": "Invalid email or password."}, status=status.HTTP_401_UNAUTHORIZED)
        if not getattr(user, "is_verified", True):
            return Response(
                {
                    "detail": "Please verify your email first. Check your inbox for the OTP.",
                    "code": "email_not_verified",
                },
                status=status.HTTP_403_FORBIDDEN,
            )
        token, _ = Token.objects.get_or_create(user=user)
        return Response(
            {
                "token": token.key,
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "alias_name": user.alias_name,
                    "phone_number": user.phone_number,
                    "is_verified": user.is_verified,
                },
            }
        )


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
            return Response({"detail": "Password must be at least 8 characters."}, status=status.HTTP_400_BAD_REQUEST)
        if not verify_otp_and_reset_password(data["email"], data["otp"], data["new_password"]):
            return Response({"detail": "Invalid or expired OTP. Request a new code."}, status=status.HTTP_400_BAD_REQUEST)
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
        return Response(
            {
                "message": "Email verified successfully.",
                "user": {
                    "id": user.id,
                    "email": user.email,
                    "first_name": user.first_name,
                    "last_name": user.last_name,
                    "alias_name": user.alias_name,
                    "phone_number": user.phone_number,
                    "is_verified": user.is_verified,
                },
            }
        )


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
        if user.is_verified:
            return Response({"detail": "Email is already verified."}, status=status.HTTP_400_BAD_REQUEST)
        create_and_send_verification_otp(user)
        return Response({"message": "Verification code sent. Check your email."})


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
        if not user:
            return Response({"detail": "User not found."}, status=status.HTTP_404_NOT_FOUND)

        return Response({"first_name": user.first_name, "last_name": user.last_name})


class ProfileMeView(RetrieveUpdateAPIView):
    serializer_class = ProfileSerializer
    permission_classes = [permissions.IsAuthenticated]
    authentication_classes = [BearerTokenAuthentication]
    parser_classes = [JSONParser, MultiPartParser, FormParser]

    def get_object(self):
        return self.request.user

    def get_serializer_class(self):
        if self.request.method.lower() == "patch":
            return ProfileUpdateSerializer
        return ProfileSerializer

    def patch(self, request, *args, **kwargs):
        serializer = self.get_serializer(self.get_object(), data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            serializer.save()
        except ValidationError as exc:
            return Response({"detail": getattr(exc, "message_dict", exc.messages)}, status=status.HTTP_400_BAD_REQUEST)
        return Response(ProfileSerializer(self.get_object()).data)


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
        items = queryset[offset : offset + limit]
        return Response(
            {
                "count": queryset.count(),
                "limit": limit,
                "offset": offset,
                "items": self.get_serializer(items, many=True).data,
            }
        )
