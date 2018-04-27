from aiida.cmdline.dbenv_lazyloading import with_dbenv
import click
import yaml
import json
from py import path as py_path  # pylint: disable=no-name-in-module,no-member

from aiida_benchmarks_vasp import computer, scf_incar, scf_potcar


TEST_SETTINGS = {
    'ADDITIONAL_RETRIEVE_LIST': ['IBZKPT'],
    'parser_settings': {'add_kpoints': True, 'add_parameters': True}
}
PERTURBED_SET_GROUPNAME = 'teststructures_Borelli_Vinay_March2018_perturbed'
UNPERTURBED_SET_GROUPNAME = 'teststructures_Borelli_Vinay_March2018'


@with_dbenv
def data_cls(class_name):
    from aiida.orm import DataFactory
    return DataFactory(class_name)


@with_dbenv
def calc_cls(class_name):
    from aiida.orm import CalculationFactory
    return CalculationFactory(class_name)


@with_dbenv
def potcar_attr(potcar, attribute):
    """Extract the number of valence electrons from a PotcarData object."""
    from aiida_vasp.io.potcar import PotcarIo

    potcar_io = PotcarIo.from_(potcar)
    return getattr(potcar_io.pymatgen, attribute)


@with_dbenv
def magnetic_info(structure, potcar_family, mapping=scf_potcar.POTCAR_MAP):
    from aiida.orm import load_node
    info_dict = load_node('8f5b7a63-07f8-4f62-8442-cb81c659170d').get_dict()
    elements = [k.symbol for k in structure.kinds]

    potcars = data_cls('vasp.potcar').get_potcars_from_structure(
        structure=structure,
        family_name=potcar_family,
        mapping=mapping
    )

    ispin = 1
    start_mag = None
    magmom = None
    if any([info_dict[e]['spin'] for e in elements]):
        ispin = 2
        start_mag = {}
        for element in elements:
            zval = potcar_attr(potcars[(element,)], 'zval')
            start_mag[element] = info_dict[element]['magmom'] / float(zval)
        magmom = []

        for site in structure.sites:
            site_element = structure.get_kind(site.kind_name).symbol
            magmom.append(start_mag[site_element])

    return ispin, magmom


@with_dbenv
def cutoff_from_structure(structure, potcar_family, mapping=scf_potcar.POTCAR_MAP):

    potcars = data_cls('vasp.potcar').get_potcars_from_structure(
        structure=structure,
        family_name=potcar_family,
        mapping=mapping
    )
    cutoffs = [potcar_attr(potcar, 'enmax') for potcar in potcars.values()]
    return max(cutoffs)


def read_experiment_yaml(filename):
    experiment_yaml = py_path.local(filename)
    experiment_data = yaml.load(experiment_yaml.read())
    return experiment_data


@click.command()
@click.option('--computer', 'computer_name', type=click.Choice(['deneb']), default=None)
@click.option('--non-perturbed', 'test_set', flag_value='non_perturbed')
@click.option('--perturbed', 'test_set', flag_value='perturbed')
@click.option('--group-name', default=None)
@click.option('--potcar-family', default=None)
@click.option('--dry-run', is_flag=True)
@click.option('--experiment', type=click.Path(dir_okay=False, exists=True, readable=True), help='a yaml file describing the experiment', default=None)
@with_dbenv
def runner(computer_name, test_set, group_name, potcar_family, dry_run, experiment):
    from aiida.orm import Code, Group, load_node
    from aiida.work import submit

    config = {}
    run_info_json = py_path.local('./run_info.json')
    cutoff = 'default'
    if experiment:
        config = read_experiment_yaml(experiment)
        if not computer_name:
            computer_name = config['computer']
        if not group_name:
            group_name = config['group_name']
        if not potcar_family:
            potcar_family = config['potcar_family']
        if 'outfile' in config:
            run_info_json = py_path.local(experiment).dirpath().join(config['outfile'])
        test_set = test_set or config.get('test_set', 'perturbed')
        cutoff = config.get('cutoff', 'default')

    cutoff_factor = 1
    if cutoff != 'default':
        cutoff_factor = int(cutoff)

    if not dry_run:
        run_info_json.ensure()
        run_info = json.loads(run_info_json.read() or '{{ "{}": {{ }} }}'.format(computer_name))
    else:
        click.echo('run_info file would be created at {}'.format(run_info_json.strpath))

    vasp_proc = calc_cls('vasp.vasp').process()
    inputs = vasp_proc.get_inputs_template()

    computer.set_options(computer=computer_name, options_template=inputs._options)
    inputs.code = Code.get_from_string('vasp@{}'.format(computer_name))
    inputs.settings = data_cls('parameter')(dict=TEST_SETTINGS)

    structures_group_name = PERTURBED_SET_GROUPNAME
    if test_set == 'non_perturbed':
        structures_group_name = UNPERTURBED_SET_GROUPNAME
    structures_group = Group.get(name=structures_group_name)

    if not dry_run:
        calc_group, created = Group.get_or_create(name=group_name)
    else:
        created = not bool(Group.query(name=group_name))
    calc_group_msg = 'Appending to {new_or_not} group {name}.'
    new_or_not = 'new' if created else 'existing'
    click.echo(calc_group_msg.format(new_or_not=new_or_not, name=group_name))

    ## limit structures if given in experiment yaml
    structures = list(structures_group.nodes)
    only_formulae = config.get('only_formulae', None)
    if only_formulae:
        structures = [structure for structure in structures if structure.get_formula() in only_formulae]

    potcar_map = scf_potcar.POTCAR_MAP

    for structure in structures:

        inputs.structure = structure
        kpoints = data_cls('array.kpoints')()
        kpoints.set_cell_from_structure(structure)
        kpoints.set_kpoints_mesh_from_density(0.15, [0]*3)
        inputs.kpoints = kpoints

        inputs.potential = data_cls('vasp.potcar').get_potcars_from_structure(
            structure=structure,
            family_name=potcar_family,
            mapping=potcar_map
        )

        ispin, magmom = magnetic_info(structure, potcar_family, potcar_map)
        incar_overrides = {}
        if ispin==1:
            magnetism_string = "non-spin-polarized"
        elif ispin==2:
            magnetism_string = "collinear-spin"
            incar_overrides['ispin'] = ispin
        else:
            raise Exception("WTF")  # This is not how you do non-collinear calcs! Set noncolin = True instead
        if magmom:
            incar_overrides['magmom'] = magmom

        if cutoff_factor != 1:
            default_enmax = cutoff_from_structure(
                structure=structure,
                potcar_family=potcar_family,
                mapping=potcar_map
            )
            incar_overrides['enmax'] = cutoff_factor * default_enmax

        inputs.parameters = scf_incar.get_scf_incar(
            inputs=inputs,
            overrides=incar_overrides
        )

        cutoff_msg = 'default'
        if cutoff_factor != 1:
            cutoff_msg = 'cutoff factor: {}'.format(cutoff_factor)

        if not dry_run:
            running_info = submit(vasp_proc, **inputs)
            running_calc = load_node(running_info.pid)
            running_calc.set_extra('magnetism', magnetism_string)
            running_calc.set_extra('cutoff', cutoff_msg)
            calc_group.add_nodes(running_calc)
            run_info[computer_name][inputs.structure.pk] = running_calc.pk
        else:
            click.echo('not submitting {}'.format(structure.get_formula()))
            from pprint import pformat
            click.echo(pformat({k: v for k, v in inputs.items()}))

    if not dry_run:
        with run_info_json.open('w') as run_info_fo:
            json.dump(run_info, run_info_fo)
