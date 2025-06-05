from typing import Dict, List


class Constants:
    STATUS_OK = 'OK'

    FULL_ACCESS: int = 0
    MEDIUM_HIGH: int = 1
    MEDIUM_ACCESS: int = 2
    MEDIUM_LOW: int = 3
    LOW_ACCESS: int = 4
    NO_ACCESS: int = 5

    ROLES: Dict[str, List[str]] = {
        FULL_ACCESS: ['all'],
        MEDIUM_HIGH: ['mediumHigh'],
        MEDIUM_ACCESS: ['medium'],
        MEDIUM_LOW: ['mediumLow'],
        LOW_ACCESS: ['low'],
        NO_ACCESS: ['none'],
    }

    ALL: int = 0
    FILTER: int = 1
    NULL: int = 2

    @classmethod
    def get_role_access(cls, role: str) -> int:
        role_access = None
        for key, roles in cls.ROLES.items():
            if role in roles:
                role_access = key
        return role_access

    @classmethod
    def get_auth_to_customers(cls, role: str) -> int:
        role_access = cls.get_role_access(role)
        auth = cls.NULL
        if role_access in [
            cls.FULL_ACCESS, cls.MEDIUM_ACCESS,
            cls.MEDIUM_HIGH, cls.MEDIUM_LOW
        ]:
            auth = cls.ALL
        elif role_access in [cls.LOW_ACCESS]:
            auth = cls.FILTER
        return auth
