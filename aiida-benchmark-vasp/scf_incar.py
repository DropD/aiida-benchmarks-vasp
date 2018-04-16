"""Input parameters for the SCF runs in this project."""
from aiida.common import constants


SCF_INCAR = {
    'prec': 'Accurate',
    'ismear': 0,
    'sigma': 0.02 * constants.ry_to_ev,
    'ediff': 1e-9,
}
