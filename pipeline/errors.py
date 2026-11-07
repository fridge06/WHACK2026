"""Pipeline exceptions."""


class GameDataError(Exception):
    """A problem with one game's data. The game is excluded with this message as the reason."""
