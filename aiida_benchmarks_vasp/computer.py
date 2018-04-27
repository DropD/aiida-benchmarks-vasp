from aiida.cmdline.dbenv_lazyloading import with_dbenv


HOUR = 3600

DENEB_OPTIONS = {
    'max_wallclock_seconds': 10*HOUR,
    'resources': {'num_machines': 1, 'num_mpiprocs_per_machine': 16},
    'queue_name': 'parallel',
    'computer': 'deneb'
}

DEFAULT_OPTIONS = DENEB_OPTIONS


@with_dbenv
def set_deneb_defaults(options_template):
    from aiida.orm import Computer

    options_template.max_wallclock_seconds = DEFAULT_OPTIONS['max_wallclock_seconds']
    options_template.resources = DEFAULT_OPTIONS['resources']
    options_template.queue_name = DEFAULT_OPTIONS['queue_name']
    options_template.computer = Computer.get(DEFAULT_OPTIONS['computer'])


@with_dbenv
def set_options(computer, options_template):
    if computer == 'deneb':
        set_deneb_defaults(options_template)
