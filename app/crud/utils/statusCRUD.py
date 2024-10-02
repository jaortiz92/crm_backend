def statusRequest() -> dict[str, bool]:
    return {
        'deleted': False,
        'elimination_allow': False,
        'value_already_registered': False,
        'there_is_key_allow': False,
        'username_or_password_ok': False
    }
