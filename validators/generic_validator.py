from .base import LanguageValidator


class GenericValidator(LanguageValidator):
    def syntax_check(self) -> None:
        # Do nothing — fallback if language unsupported
        pass
