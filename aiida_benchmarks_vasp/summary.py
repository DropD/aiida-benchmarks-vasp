import re

from aiida.cmdline.dbenv_lazyloading import with_dbenv
import click
from py import path as py_path  # pylint: disable=no-name-in-module,no-member


def sanity_checks(calc):
    sanity = True
    if calc.get_state() not in ['FINISHED', 'PARSINGFAILED']:
        click.echo('Calculation state is {}: skipping'.format(calc.get_state()))
        sanity = False
    
    if vasprun_data(calc) == -1:
        click.echo('Vasprun could not be read {}: skipping'.format(calc.get_state()))
        sanity = False
    return sanity


def vasprun_data(calc):
    from aiida_vasp.io.vasprun import VasprunParser
    if not hasattr(vasprun_data, 'cache'):
        vasprun_data.cache = {}
    if not calc.uuid in vasprun_data.cache:
        try:
            vasprun_file = py_path.local(calc.out.retrieved.get_abs_path()).join('path', 'vasprun.xml')
            vasprun_data.cache[calc.uuid] = VasprunParser(vasprun_file.strpath)
        except Exception as err:
            click.echo(err, err=True)
            return None
    return vasprun_data.cache[calc.uuid]


def calc_sorting_keys(calc):
    """Keys in order of importance for sorting: nspins, nions, formula, runtime."""
    vasprun = vasprun_data(calc)
    sorting_keys = (
        vasprun.bands.shape[0] if vasprun else calc.inp.parameters.get_dict().get('ispin', 1),  # number of spin components ?
        len(calc.inp.structure.sites),
        calc.inp.structure.get_formula(),
        float(vasprun._i('ENMAX')) if vasprun else 0.0,
        float(wall_clock_time(calc))
    )
    return sorting_keys


def outcar_data(calc):
    if not hasattr(outcar_data, 'cache'):
        outcar_data.cache = {}
    if not calc.uuid in outcar_data.cache:
        outcar_file = py_path.local(calc.out.retrieved.get_abs_path()).join('path', 'OUTCAR')
        outcar_data.cache[calc.uuid] = outcar_file.read()
    return outcar_data.cache[calc.uuid]


def cell_symmetries(calc):
    """Retrieve number of space group operations and point group."""
    outcar_content = outcar_data(calc)

    space_group_hits = re.findall(r'Found\s*(\d+) space group operations', outcar_content)
    num_space_group_operations = max([int(i) for i in space_group_hits])

    point_symmetry_hits = re.findall(r'point symmetry (.*?)\s*\.', outcar_content)
    point_symmetry = point_symmetry_hits[0]

    point_group_hits = re.findall(r'space group is (.*?)\s*\.', outcar_content)
    point_group = point_group_hits[0] if point_group_hits else ''

    return num_space_group_operations, point_symmetry, point_group


def wall_clock_time(calc):
    """Retrieve "Elapsed Time" from OUTCAR."""
    outcar_content = outcar_data(calc)

    elapsed_time = re.findall(r'Elapsed time \(sec\):\s*([\d.]*?)\s', outcar_content)
    return elapsed_time[0] if elapsed_time else 0


def out_node(calc, link_name):
    output_dict = calc.get_outputs_dict()
    res = output_dict.get(link_name, None)
    if not res:
        parser = calc.get_parserclass()(calc=calc)
        success, out_items = parser.parse_from_calc()
        if success:
            out_dict = dict(out_items)
            res = out_dict.get(link_name, None)
    return res


def free_energy(calc):
    calc_res = out_node(calc, 'output_parameters').get_dict()
    result = None
    if calc_res:
        result = calc_res.get('free_energy', None)
        if not result:
            result = calc_res.get('energies', {}).get('free_energy', None)

    if not result:
        vasprun = vasprun_data(calc)
        result = vasprun._i('e_fr_energy', path='//calculation/energy/')
    return result


@click.command()
@click.option('-G', '--group', 'group_names', multiple=True)
@with_dbenv
def summary(group_names):
    from aiida.orm import Group

    groups = [Group.get(name=name) for name in group_names]

    for group in groups:
        click.echo(group)
        click.echo('')
        for calc in sorted(group.nodes, key=calc_sorting_keys):
            calc_vasprun = vasprun_data(calc)
            output_kpoints = out_node(calc, 'output_kpoints')
            results = out_node(calc, 'output_parameters').get_dict()
            click.echo('=== {} - {} ==='.format(
                calc.pk, calc.inp.structure.get_formula()))
            if not sanity_checks(calc):
                click.echo('')
                continue
            click.echo('Number of atoms / electrons: {}/{}'.format(
                len(calc.inp.structure.sites),
                calc_vasprun._i('NELECT'))
            )
            click.echo('POTCARs:')
            for link_name, node in calc.get_inputs_dict().items():
                if 'potential' in link_name.lower():
                    click.echo('{}: {} ({})'.format(
                        link_name.lstrip('potential_'),
                        node.full_name, node.md5)
                    )
            click.echo('Cutoff (rho/wfc) (eV): {}'.format(
                calc_vasprun._i('ENMAX')))
            kpoints_mesh = calc.inp.kpoints.get_kpoints_mesh()
            click.echo('Input k-point mesh: {} offset: {}'.format(
                kpoints_mesh[0], kpoints_mesh[1]))
            click.echo('Computed k-points: {}'.format(
                output_kpoints.get_kpoints().shape[0]))
            click.echo('Total energy (eV): {}'.format(free_energy(calc)))
            click.echo('Total forces (eV/Angstrom):\n{}'.format(
                calc_vasprun._varray('forces')))
            click.echo('Total stress (kBar):\n{}'.format(
                calc_vasprun._varray('stress')))
            num_symmetries, point_sym, point_group = cell_symmetries(calc)
            point_group_str = ' ({})'.format(point_group) if point_group else ''
            click.echo('Cell symmetries: {}'.format(num_symmetries))
            click.echo('VASP computed point group(s): {}{}'.format(
                point_sym, point_group_str))
            click.echo('Magnetic treatment: {} ({} spin components)'.format(
                calc.get_extra('magnetism'), calc_vasprun.bands.shape[0]))
            num_scf_steps = len(calc_vasprun.tree.findall('//scstep'))
            click.echo('Number of SCF iterations (total): {} ({})'.format(
                num_scf_steps, num_scf_steps))
            click.echo('Wall-clock time: {}'.format(wall_clock_time(calc)))
            click.echo('')
