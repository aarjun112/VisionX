from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User


class SignUpForm(UserCreationForm):
    class Meta(UserCreationForm.Meta):
        model = User
        fields = ('username',)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Remove all the small grey help text
        for field in self.fields.values():
            field.help_text = ''

        self.fields['username'].label = 'Username'
        self.fields['username'].widget.attrs.update({
            'placeholder': 'Choose a username',
            'autocomplete': 'username',
            'autofocus': True,
        })
        self.fields['password1'].label = 'Password'
        self.fields['password1'].widget.attrs.update({
            'placeholder': 'Create a password',
            'autocomplete': 'new-password',
        })
        self.fields['password2'].label = 'Confirm password'
        self.fields['password2'].widget.attrs.update({
            'placeholder': 'Type it again',
            'autocomplete': 'new-password',
        })