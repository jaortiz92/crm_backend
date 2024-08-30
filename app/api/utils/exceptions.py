from fastapi import HTTPException, status

class Exceptions:
    
    def register_not_found(register: str, value: str) -> None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"{register} with reference '{value}' does not exist"
        )
