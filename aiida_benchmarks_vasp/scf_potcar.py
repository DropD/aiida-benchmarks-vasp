from aiida_vasp.utils.default_paws import DEFAULT_GW


__all__ = ['POTCAR_MAP']

POTCAR_MAP = {key: value+'_GW' for key, value in DEFAULT_GW.items()}
