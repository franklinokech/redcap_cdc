# from cryptography.fernet import Fernet
# from django.conf import settings
#
# cipher = Fernet(settings.FERNET_KEY.encode())
#
# def encrypt(value: str) -> str:
#     return cipher.encrypt(value.encode()).decode()
# def decrypt(value: str) -> str:
#     return cipher.decrypt(value.encode()).decode()