class ServiceError(Exception):
    """Business error with an HTTP status and a Vietnamese message for the UI."""

    def __init__(self, status_code, message, code='error', details=None):
        super().__init__(message)
        self.status_code = status_code
        self.message = message
        self.code = code
        self.details = details


def not_found(message='Không tìm thấy dữ liệu.'):
    return ServiceError(404, message, 'not_found')


def conflict(message, code='conflict', details=None):
    return ServiceError(409, message, code, details)


def invalid(message, code='invalid', details=None):
    return ServiceError(422, message, code, details)
