"""Input parameters for the SCF runs in this project."""
from numpy import sqrt

from aiida.cmdline.dbenv_lazyloading import with_dbenv
from aiida.common import constants


SCF_INCAR = {
    'prec': 'Accurate',
    'ismear': 0,
    'sigma': 0.02 * constants.ry_to_ev,
    'ediff': 1e-9,
}


@with_dbenv
def get_scf_incar(inputs=None, overrides=None):
    from aiida.orm import DataFactory

    scf_incar = SCF_INCAR.copy()
    if inputs:
        resources = inputs._options.get('resources', {})
        ncores = resources.get('num_mpiprocs_per_machine', None)

        if ncores:
            scf_incar['ncore'] = int(sqrt(ncores))

    if overrides:
        scf_incar.update(overrides)

    return DataFactory('parameter')(dict=scf_incar)
