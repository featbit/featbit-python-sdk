class Category:
    """
    This class is used only by the internals of the feature flag storage mechanism.
    This type will be passed to the feature flag storage methods;
    its ``name`` property tells the feature store which collection of data is being referenced ("featureflags", "segments", etc.)
    The purpose is for the storage module to store data as completely generic JSON database
    """

    def __init__(self, name, tag):
        self._name = name
        self._tag = tag

    @property
    def name(self):
        return self._name

    @property
    def tag(self):
        return self._tag


FEATURE_FLAGS = Category('featureFlags', 'ff')

SEGMENTS = Category('segments', 'seg')

DATATEST = Category('datatest', 'test')

"""
An enumeration of all supported types. Applications should not need to reference this object directly.
Custom data storage implementations can determine what kinds of model objects may need to be stored.
"""
ALL_CATS = [FEATURE_FLAGS, SEGMENTS, DATATEST]

ALL_CAT_NAMES = ['featureFlags', 'segments', 'datatest']
