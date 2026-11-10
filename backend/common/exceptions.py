"""Map the imported A and B business errors to the shared API envelope."""

from common.errors import AppError


class BusinessError(AppError):
    def __init__(self, code, message, status=409):
        super().__init__(status, code, message)


class ApiError(AppError):
    def __init__(self, status_code, code, message, errors=None, headers=None):
        super().__init__(status_code, code, message, errors=errors, headers=headers)
