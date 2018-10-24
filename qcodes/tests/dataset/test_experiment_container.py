import pytest

from qcodes.dataset.database import get_DB_location
from qcodes.dataset.experiment_container import (load_experiment_by_name,
                                                 new_experiment,
                                                 load_or_create_experiment,
                                                 experiments,
                                                 load_experiment,
                                                 Experiment,
                                                 load_last_experiment)
from qcodes.dataset.measurements import Measurement
# pylint: disable=unused-import
from qcodes.tests.dataset.temporary_databases import empty_temp_db, dataset, \
    experiment


def assert_experiments_equal(exp, exp_2):
    for attr in ['name', 'sample_name', 'path_to_db', 'last_counter']:
        assert getattr(exp, attr) == getattr(exp_2, attr)
    assert len(exp_2) == len(exp)
    assert repr(exp_2) == repr(exp)


@pytest.mark.usefixtures("empty_temp_db")
def test_run_loaded_experiment():
    """
    Test that we can resume a measurement after loading by name
    """
    new_experiment("test", "test1")
    exp_loaded = load_experiment_by_name("test", "test1")

    meas = Measurement(exp=exp_loaded)
    with meas.run():
        pass

    with meas.run():
        pass

def test_last_data_set_from_experiment(dataset):
    experiment = load_experiment(dataset.exp_id)
    ds = experiment.last_data_set()

    assert dataset.run_id == ds.run_id
    assert dataset.name == ds.name
    assert dataset.exp_id == ds.exp_id
    assert dataset.exp_name == ds.exp_name
    assert dataset.sample_name == ds.sample_name
    assert dataset.path_to_db == ds.path_to_db

    assert experiment.path_to_db == ds.path_to_db


def test_last_data_set_from_experiment_with_no_datasets(experiment):
    with pytest.raises(ValueError, match='There are no runs in this '
                                         'experiment'):
        _ = experiment.last_data_set()


@pytest.mark.usefixtures("empty_temp_db")
def test_load_or_create_experiment_loading():
    """Test that an experiment is correctly loaded"""
    exp = new_experiment("experiment_name", "sample_name")
    exp_2 = load_or_create_experiment("experiment_name", "sample_name")
    assert_experiments_equal(exp, exp_2)


@pytest.mark.usefixtures("empty_temp_db")
def test_load_or_create_experiment_different_sample_name():
    """
    Test that an experiment is created for the case when the experiment
    name is the same, but the sample name is different
    """
    exp = new_experiment("experiment_name", "sample_name_1")
    exp_2 = load_or_create_experiment("experiment_name", "sample_name_2")

    actual_experiments = experiments()
    assert len(actual_experiments) == 2

    assert exp.name == exp_2.name
    assert exp.sample_name != exp_2.sample_name


@pytest.mark.usefixtures("empty_temp_db")
def test_load_or_create_experiment_creating():
    """Test that an experiment is correctly created"""
    exp = load_or_create_experiment("experiment_name", "sample_name")
    exp_2 = load_experiment_by_name("experiment_name", "sample_name")
    assert_experiments_equal(exp, exp_2)


@pytest.mark.usefixtures("empty_temp_db")
def test_load_or_create_experiment_creating_not_empty():
    """Test that an experiment is correctly created when DB is not empty"""
    exp = load_or_create_experiment("experiment_name_1", "sample_name_1")
    exp_2 = load_or_create_experiment("experiment_name_2", "sample_name_2")

    actual_experiments = experiments()
    assert len(actual_experiments) == 2

    assert_experiments_equal(actual_experiments[0], exp)
    assert_experiments_equal(actual_experiments[1], exp_2)


@pytest.mark.usefixtures("empty_temp_db")
def test_has_attributes_after_init():
    """
    Ensure that all attributes are populated after __init__ in BOTH cases
    (exp_id is None / exp_id is not None)
    """

    attrs = ['name', 'exp_id', '_exp_id', 'sample_name', 'last_counter',
             'path_to_db', '_path_to_db', 'conn', 'started_at',
             'finished_at', 'format_string']

    # This creates an experiment in the db
    exp1 = Experiment(exp_id=None)

    # This loads the experiment that we just created
    exp2 = Experiment(exp_id=1)

    for exp in (exp1, exp2):
        for attr in attrs:
            assert hasattr(exp, attr)
            getattr(exp, attr)


def test_experiment_read_only_properties(experiment):
    read_only_props = ['name', 'exp_id', 'sample_name', 'last_counter',
                       'path_to_db', 'started_at', 'finished_at',
                       'format_string']

    for prop in read_only_props:
        with pytest.raises(AttributeError, match="can't set attribute",
                           message=f"It is not expected to be possible to set "
                                   f"property {prop!r}"):
            setattr(experiment, prop, True)


@pytest.mark.usefixtures("empty_temp_db")
@pytest.mark.parametrize("non_existing_id", (1, 0, -1, 'number#42'))
def test_create_experiment_from_non_existing_id(non_existing_id):
    with pytest.raises(ValueError, match="No such experiment in the database"):
        _ = Experiment(exp_id=non_existing_id)


@pytest.mark.usefixtures("empty_temp_db")
@pytest.mark.parametrize("non_existing_id", (1, 0, -1))
def test_load_experiment_from_non_existing_id(non_existing_id):
    with pytest.raises(ValueError, match="No such experiment in the database"):
        _ = load_experiment(non_existing_id)


@pytest.mark.usefixtures("empty_temp_db")
@pytest.mark.parametrize("bad_id", (None, 'number#42'))
def test_load_experiment_from_bad_id(bad_id):
    with pytest.raises(ValueError, match="Experiment ID must be an integer"):
        _ = load_experiment(bad_id)


def test_format_string(empty_temp_db):
    # default format string
    exp1 = Experiment(exp_id=None)
    assert "{}-{}-{}" == exp1.format_string

    # custom format string
    fmt_str = "name_{}__id_{}__run_cnt_{}"
    exp2 = Experiment(exp_id=None, format_string=fmt_str)
    assert fmt_str == exp2.format_string

    # invalid format string
    fmt_str = "name_{}__id_{}__{}__{}"
    with pytest.raises(ValueError, match=r"Invalid format string. Can not "
                                         r"format \(name, exp_id, "
                                         r"run_counter\)"):
        _ = Experiment(exp_id=None, format_string=fmt_str)


def test_load_last_experiment(empty_temp_db):
    # test in case of no experiments
    with pytest.raises(ValueError, match='There are no experiments in the '
                                         'database file'):
        _ = load_last_experiment()

    # create 2 experiments
    exp1 = Experiment(exp_id=None)
    exp2 = Experiment(exp_id=None)
    assert get_DB_location() == exp1.path_to_db
    assert get_DB_location() == exp2.path_to_db

    # load last and assert that its the 2nd one that was created
    last_exp = load_last_experiment()
    assert last_exp.exp_id == exp2.exp_id
    assert last_exp.exp_id != exp1.exp_id
    assert last_exp.path_to_db == exp2.path_to_db
