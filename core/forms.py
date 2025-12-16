from django import forms
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User

from .models import Deal, Message, ShyRequest


class MultiFileInput(forms.ClearableFileInput):
    allow_multiple_selected = True


class ShyRequestForm(forms.ModelForm):
    attachments = forms.FileField(
        required=False,
        widget=MultiFileInput(),
        help_text="Add any images, videos, or documents that support the request.",
    )

    class Meta:
        model = ShyRequest
        fields = [
            "requester_name",
            "requester_email",
            "requester_phone",
            "target_name",
            "target_email",
            "target_phone",
            "target_address",
            "description",
            "service_channel",
            "call_minutes",
        ]
        widgets = {
            "requester_name": forms.TextInput(attrs={
                "class": "input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg"
            }),
            "requester_email": forms.EmailInput(attrs={
                "class": "input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg"
            }),
            "requester_phone": forms.TextInput(attrs={
                "class": "input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg"
            }),
            "target_name": forms.TextInput(attrs={
                "class": "input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg"
            }),
            "target_email": forms.EmailInput(attrs={
                "class": "input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg"
            }),
            "target_phone": forms.TextInput(attrs={
                "class": "input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg"
            }),
            "target_address": forms.TextInput(attrs={
                "class": "input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg"
            }),
            "description": forms.Textarea(attrs={
                "rows": 6,
                "class": "textarea textarea-bordered border-4 border-black rounded-xl p-4 text-lg font-semibold w-full bg-white shadow-lg"
            }),
            "service_channel": forms.Select(attrs={
                "class": "select select-bordered border-4 border-black rounded-xl p-3 text-lg font-bold w-full bg-white shadow-lg"
            }),
            "call_minutes": forms.NumberInput(attrs={
                "class": "input input-bordered border-4 border-black rounded-xl p-3 text-lg font-semibold w-full bg-white shadow-lg"
            }),
        }

    def clean_call_minutes(self):
        minutes = self.cleaned_data.get("call_minutes") or 0
        channel = self.cleaned_data.get("service_channel")
        if channel != ShyRequest.ServiceChannel.CALL:
            return 0
        return minutes


class SignUpForm(UserCreationForm):
    email = forms.EmailField(required=True)

    class Meta:
        model = User
        fields = ("username", "email", "password1", "password2")

    def save(self, commit=True):
        user = super().save(commit=False)
        user.email = self.cleaned_data["email"]
        if commit:
            user.save()
        return user


class MessageForm(forms.ModelForm):
    class Meta:
        model = Message
        fields = ["body"]
        widgets = {
            "body": forms.Textarea(attrs={
                "rows": 2,
                "placeholder": "Type your message...",
                "class": "textarea textarea-bordered border-4 border-black rounded-xl p-3 text-base font-semibold w-full bg-white shadow-lg resize-none"
            })
        }


class DealForm(forms.ModelForm):
    class Meta:
        model = Deal
        fields = ["amount", "currency", "payer"]
        widgets = {
            "amount": forms.NumberInput(attrs={
                "step": "0.01",
                "min": "0",
                "class": "input input-bordered border-4 border-black rounded-xl p-3 text-lg font-bold w-full bg-white shadow-lg"
            }),
            "currency": forms.Select(attrs={
                "class": "select select-bordered border-4 border-black rounded-xl p-3 text-lg font-bold w-full bg-white shadow-lg"
            }),
            "payer": forms.Select(attrs={
                "class": "select select-bordered border-4 border-black rounded-xl p-3 text-lg font-bold w-full bg-white shadow-lg"
            }),
        }

