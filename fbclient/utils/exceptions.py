class UnSucessfulHttpRequestException(Exception):

    def __init__(self, status):
        super().__init__('http request error = %d' % status)
        self.__status = status

    @property
    def status(self) -> int:
        return self.__status


class DataNotValidException(Exception):

    def __init__(self, msg):
        super().__init__(msg)
