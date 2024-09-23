def statusRequest() -> dict[str, bool]:
    return {
        'deleted': False,
        'elimination_allow': False,
        'there_is_key_allow': False,
        'user_already_registered': False,
    }
