from django import forms
from django.contrib.auth.forms import UserCreationForm, UserChangeForm
from django.contrib.auth import get_user_model

from .validators import PhoneNumberValidator

User = get_user_model()


class CustomUserCreationForm(UserCreationForm):
    """
    Form for creating a new user account.
    """
    email = forms.EmailField(
        required=True,
        widget=forms.EmailInput(attrs={
            'class': 'input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg',
            'placeholder': 'Enter your email address'
        })
    )
    first_name = forms.CharField(
        required=True,
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg',
            'placeholder': 'Enter your first name'
        })
    )
    last_name = forms.CharField(
        required=True,
        max_length=150,
        widget=forms.TextInput(attrs={
            'class': 'input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg',
            'placeholder': 'Enter your last name'
        })
    )
    alias_name = forms.CharField(
        required=False,
        max_length=150,
        help_text='Optional display name or nickname.',
        widget=forms.TextInput(attrs={
            'class': 'input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg',
            'placeholder': 'Enter an alias name (optional)'
        })
    )
    phone_number = forms.CharField(
        required=False,
        max_length=20,
        validators=[PhoneNumberValidator()],
        help_text='Phone number in international format (e.g., +41 79 123 4567). Must start with + and country code.',
        widget=forms.TextInput(attrs={
            'class': 'input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg',
            'placeholder': '+41 79 123 4567'
        })
    )

    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'alias_name', 'phone_number', 'password1', 'password2')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Style password fields
        self.fields['password1'].widget.attrs.update({
            'class': 'input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg',
            'placeholder': 'Enter password'
        })
        self.fields['password2'].widget.attrs.update({
            'class': 'input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg',
            'placeholder': 'Confirm password'
        })

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data['email']
        user.first_name = self.cleaned_data['first_name']
        user.last_name = self.cleaned_data['last_name']
        user.alias_name = self.cleaned_data.get('alias_name', '')
        user.phone_number = self.cleaned_data.get('phone_number', '')
        if commit:
            user.save()
        return user


class CustomUserChangeForm(UserChangeForm):
    """
    Form for updating user information.
    """
    class Meta:
        model = User
        fields = ('email', 'first_name', 'last_name', 'alias_name', 'phone_number', 'profile_picture', 'is_active', 'is_staff')


class SignUpForm(CustomUserCreationForm):
    """
    Alias for CustomUserCreationForm for backward compatibility.
    """
    pass

