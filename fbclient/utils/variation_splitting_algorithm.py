
import hashlib
from typing import List

__MIN_INT__ = -2147483648


class VariationSplittingAlgorithm:
    def __init__(self, key: str, percentage_range: List[float]):
        self.__key = key
        self.__percentage_range = percentage_range

    def is_key_belongs_to_percentage(self) -> bool:
        try:
            if self.__percentage_range[0] == 0 and self.__percentage_range[1] == 1:
                return True
            percentage = self.__percentage_of_key()
            return percentage >= self.__percentage_range[0] and percentage < self.__percentage_range[1]
        except:
            return False

    def __percentage_of_key(self) -> float:
        digest = hashlib.md5(self.__key.encode(encoding='utf-8')).digest()
        magic_num = int.from_bytes(digest[:4], byteorder='little', signed=True)
        return abs(magic_num / __MIN_INT__)
