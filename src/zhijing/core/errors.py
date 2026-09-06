class DomainError(Exception):
    """可安全返回给客户端的业务错误。"""

    def __init__(self, code: str, message: str, status: int = 400):
        super().__init__(message)
        self.code = code
        self.message = message
        self.status = status
