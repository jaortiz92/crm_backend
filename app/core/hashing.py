from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError

ph = PasswordHasher()


def get_password_hash(password: str) -> str:
    return ph.hash(password.encode("utf-8"))


def verify_password(hashed_password: str, plain_password: str) -> bool:
    try:
        return ph.verify(hashed_password, plain_password.encode("utf-8"))
    except VerifyMismatchError:
        return False
