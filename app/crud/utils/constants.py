from typing import Dict, List


class Constants:
    STATUS_OK = 'OK'

    FULL_ACCESS: int = 0
    MEDIUM_ACCESS: int = 1
    LOW_ACCESS: int = 2
    NO_ACCESS: int = 3

    ROLES: Dict[str, List[str]] = {
        FULL_ACCESS: ['all'],
        MEDIUM_ACCESS: ['medium'],
        LOW_ACCESS: ['comercial'],
        NO_ACCESS: ['ninguno'],
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
        if role_access in [cls.FULL_ACCESS, cls.MEDIUM_ACCESS]:
            auth = cls.ALL
        elif role_access in [cls.LOW_ACCESS]:
            auth = cls.FILTER
        return auth
