import json
import tempfile
from contextlib import contextmanager
from pathlib import Path
from tempfile import mkdtemp
from typing import Dict, Optional

import ape
import pytest
import yaml
from _pytest.runner import pytest_runtest_makereport as orig_pytest_runtest_makereport
from ape.contracts import ContractContainer
from ape.exceptions import APINotImplementedError, UnknownSnapshotError
from ape.managers.config import CONFIG_FILE_NAME
from ethpm_types import ContractType

from ape_hardhat import HardhatProvider

# NOTE: Ensure that we don't use local paths for the DATA FOLDER
ape.config.DATA_FOLDER = Path(mkdtemp()).resolve()

BASE_CONTRACTS_PATH = Path(__file__).parent / "data" / "contracts"
NAME = "hardhat"

# Needed to test tracing support in core `ape test` command.
pytest_plugins = ["pytester"]
MAINNET_FORK_PORT = 9001
GOERLI_FORK_PORT = 9002


def pytest_runtest_makereport(item, call):
    tr = orig_pytest_runtest_makereport(item, call)
    if call.excinfo is not None and "too many requests" in str(call.excinfo).lower():
        tr.outcome = "skipped"
        tr.wasxfail = "reason: Alchemy requests overloaded (likely in CI)"

    return tr


@pytest.fixture(scope="session")
def name():
    return NAME


@pytest.fixture(scope="session", autouse=True)
def in_tests_dir(config):
    with config.using_project(Path(__file__).parent):
        yield


@contextmanager
def _isolation():
    if ape.networks.active_provider is None:
        raise AssertionError("Isolation should only be used with a connected provider.")

    init_network_name = ape.chain.provider.network.name
    init_provider_name = ape.chain.provider.name

    try:
        snapshot = ape.chain.snapshot()
    except APINotImplementedError:
        # Provider not used or connected in test.
        snapshot = None

    yield

    if (
        snapshot is None
        or ape.networks.active_provider is None
        or ape.chain.provider.network.name != init_network_name
        or ape.chain.provider.name != init_provider_name
    ):
        return

    try:
        ape.chain.restore(snapshot)
    except UnknownSnapshotError:
        # Assume snapshot removed for testing reasons
        # or the provider was not needed to be connected for the test.
        pass


@pytest.fixture(autouse=True)
def main_provider_isolation(connected_provider):
    with _isolation():
        yield


@pytest.fixture(scope="session")
def config():
    return ape.config


@pytest.fixture(scope="session")
def project():
    return ape.project


@pytest.fixture(scope="session")
def accounts():
    return ape.accounts.test_accounts


@pytest.fixture(scope="session")
def convert():
    return ape.convert


@pytest.fixture(scope="session")
def networks():
    return ape.networks


@pytest.fixture(params=("solidity", "vyper"))
def contract_type(request, get_contract_type) -> ContractType:
    return get_contract_type(f"{request.param}_contract")


@pytest.fixture
def get_contract_type():
    def fn(name: str):
        path = BASE_CONTRACTS_PATH / "ethereum" / "local" / f"{name}.json"
        content = path.read_text()
        return ContractType.parse_raw(content)

    return fn


@pytest.fixture
def contract_container(contract_type) -> ContractContainer:
    return ContractContainer(contract_type=contract_type)


@pytest.fixture
def contract_instance(owner, contract_container, connected_provider):
    return owner.deploy(contract_container)


@pytest.fixture(scope="session")
def sender(accounts):
    return accounts[0]


@pytest.fixture(scope="session")
def receiver(accounts):
    return accounts[1]


@pytest.fixture(scope="session")
def owner(accounts):
    return accounts[2]


@pytest.fixture(scope="session")
def local_network_api(networks):
    return networks.ethereum.local


@pytest.fixture
def connected_provider(name, networks, local_network_api):
    with networks.ethereum.local.use_provider(name) as provider:
        yield provider


@pytest.fixture(scope="session")
def disconnected_provider(name, local_network_api):
    return HardhatProvider(
        name=name,
        network=local_network_api,
        request_header={},
        data_folder=Path("."),
        provider_settings={},
    )


@pytest.fixture
def mainnet_fork_port():
    return MAINNET_FORK_PORT


@pytest.fixture
def mainnet_fork_provider(name, networks, mainnet_fork_port):
    with networks.ethereum["mainnet-fork"].use_provider(
        name, provider_settings={"port": mainnet_fork_port}
    ) as provider:
        yield provider


@pytest.fixture
def goerli_fork_port():
    return GOERLI_FORK_PORT


@pytest.fixture
def goerli_fork_provider(name, networks, goerli_fork_port):
    with networks.ethereum.goerli_fork.use_provider(
        name, provider_settings={"port": goerli_fork_port}
    ) as provider:
        yield provider


@pytest.fixture(scope="session")
def temp_config(config):
    @contextmanager
    def func(data: Dict, package_json: Optional[Dict] = None):
        with tempfile.TemporaryDirectory() as temp_dir_str:
            temp_dir = Path(temp_dir_str)

            config._cached_configs = {}
            config_file = temp_dir / CONFIG_FILE_NAME
            config_file.touch()
            config_file.write_text(yaml.dump(data))
            config.load(force_reload=True)

            if package_json:
                package_json_file = temp_dir / "package.json"
                package_json_file.write_text(json.dumps(package_json))

            with config.using_project(temp_dir):
                yield temp_dir

            config_file.unlink()
            config._cached_configs = {}

    return func
