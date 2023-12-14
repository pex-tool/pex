from pex.pep_427 import InstallableType


def get_installable_type_flag(installable_type):
    # type: (InstallableType.Value) -> str
    return (
        "--no-pre-install-wheels"
        if installable_type is InstallableType.WHEEL_FILE
        else "--pre-install-wheels"
    )
