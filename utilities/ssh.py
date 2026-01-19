"""SSH utilities using OpenSSH via virtctl ssh.

This module replaces paramiko/rrmngmnt SSH functionality with OpenSSH
executed through `virtctl ssh`, providing better stability and compatibility.
"""

from __future__ import annotations

import logging
import os
import shlex
import subprocess
from dataclasses import dataclass
from typing import TYPE_CHECKING, NamedTuple

from pyhelper_utils.shell import run_command as shell_run_command
from timeout_sampler import TimeoutSampler

from utilities.constants import (
    CNV_VM_SSH_KEY_PATH,
    FLAVORS_EXCLUDED_FROM_CLOUD_INIT,
    TIMEOUT_1MIN,
    TIMEOUT_2MIN,
    VIRTCTL,
)

if TYPE_CHECKING:
    from utilities.virt import VirtualMachineForTests

LOGGER = logging.getLogger(__name__)


class SSHCommandError(Exception):
    """Exception raised when SSH command execution fails."""

    def __init__(
        self,
        message: str,
        returncode: int | None = None,
        stdout: str = "",
        stderr: str = "",
    ) -> None:
        """Initialize SSHCommandError.

        Args:
            message: Error description.
            returncode: Command exit code.
            stdout: Standard output from command.
            stderr: Standard error from command.
        """
        super().__init__(message)
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


class SSHConnectionError(Exception):
    """Exception raised when SSH connection fails."""


class KernelInfo(NamedTuple):
    """Kernel information structure."""

    release: str
    version: str
    type: str


class TimezoneInfo(NamedTuple):
    """Timezone information structure."""

    name: str
    offset: str


@dataclass(frozen=True)
class CommandResult:
    """Result of an SSH command execution."""

    returncode: int
    stdout: str
    stderr: str

    def __iter__(self):
        """Allow tuple unpacking: rc, out, err = result."""
        return iter((self.returncode, self.stdout, self.stderr))


def _get_ssh_key_path() -> str | None:
    """Get the SSH private key path from environment.

    Returns:
        Path to SSH private key or None if not set.
    """
    return os.environ.get(CNV_VM_SSH_KEY_PATH)


def _should_use_ssh_key(vm: VirtualMachineForTests) -> bool:
    """Check if VM should use SSH key authentication.

    Windows and Cirros VMs don't support SSH key via cloud-init,
    so they use password authentication instead.

    Args:
        vm: VirtualMachine object.

    Returns:
        True if VM should use SSH key, False for password-based auth.
    """
    os_flavor = getattr(vm, "os_flavor", "")
    return not any(flavor in os_flavor for flavor in FLAVORS_EXCLUDED_FROM_CLOUD_INIT)


def _parse_timezone_offset(offset_str: str) -> int:
    """Parse timezone offset string to seconds.

    Args:
        offset_str: Timezone offset from 'date +%z' (e.g., "+0530", "-0800").

    Returns:
        Offset in seconds (positive for east of UTC, negative for west).

    Raises:
        ValueError: If offset_str format is invalid.
    """
    if not offset_str or len(offset_str) != 5:
        raise ValueError(f"Invalid timezone offset format: {offset_str}")

    sign = 1 if offset_str[0] == "+" else -1
    hours = int(offset_str[1:3])
    minutes = int(offset_str[3:5])

    return sign * (hours * 3600 + minutes * 60)


def _build_virtctl_ssh_command(
    vm_name: str,
    namespace: str,
    username: str,
    command: str,
    ssh_key_path: str | None = None,
) -> list[str]:
    """Build the virtctl ssh command with proper options.

    Args:
        vm_name: Name of the virtual machine.
        namespace: Namespace where the VM resides.
        username: SSH username.
        command: Command to execute on the VM.
        ssh_key_path: Path to SSH private key (optional).

    Returns:
        List of command arguments for subprocess.
    """
    cmd = [
        VIRTCTL,
        "ssh",
        "-l",
        username,
        f"vmi/{vm_name}",
        "-n",
        namespace,
        "--command",
        command,
        "--local-ssh-opts=-o StrictHostKeyChecking=no",
        "--local-ssh-opts=-o UserKnownHostsFile=/dev/null",
        "--local-ssh-opts=-o LogLevel=ERROR",
    ]

    if ssh_key_path:
        cmd.extend(["--identity-file", ssh_key_path])

    return cmd


def _get_vm_credentials(vm: VirtualMachineForTests) -> tuple[str, str | None]:
    """Extract username and password from VM.

    Args:
        vm: VirtualMachine object.

    Returns:
        Tuple of (username, password or None).
    """
    username = getattr(vm, "username", None) or vm.login_params.get("username", "")
    password = getattr(vm, "password", None) or vm.login_params.get("password")
    return username, password


def run_command(
    vm: VirtualMachineForTests,
    command: str | list[str],
    timeout: int | float = TIMEOUT_1MIN,
    check: bool = False,
) -> CommandResult:
    """Execute a command on the VM via virtctl ssh.

    Args:
        vm: VirtualMachine object.
        command: Command to execute (string or list of arguments).
        timeout: Command timeout in seconds.
        check: If True, raise SSHCommandError on non-zero exit code.

    Returns:
        CommandResult with returncode, stdout, and stderr.

    Raises:
        SSHCommandError: If check=True and command returns non-zero exit code.
        SSHConnectionError: If SSH connection fails.
    """
    if isinstance(command, list):
        command_str = shlex.join(command)
    else:
        command_str = command

    username, _ = _get_vm_credentials(vm=vm)
    ssh_key_path = _get_ssh_key_path() if _should_use_ssh_key(vm=vm) else None

    virtctl_cmd = _build_virtctl_ssh_command(
        vm_name=vm.name,
        namespace=vm.namespace,
        username=username,
        command=command_str,
        ssh_key_path=ssh_key_path,
    )

    LOGGER.info(
        "Executing SSH command",
        extra={"vm": vm.name, "namespace": vm.namespace, "command": command_str},
    )

    try:
        success, stdout, stderr = shell_run_command(
            command=virtctl_cmd,
            check=False,
            verify_stderr=False,
            timeout=int(timeout),
        )

        returncode = 0 if success else 1
        cmd_result = CommandResult(
            returncode=returncode,
            stdout=stdout,
            stderr=stderr,
        )

        if check and returncode != 0:
            raise SSHCommandError(
                message=f"Command failed with exit code {returncode}: {command_str}",
                returncode=returncode,
                stdout=stdout,
                stderr=stderr,
            )

        return cmd_result

    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        raise SSHCommandError(
            message=f"Command timed out after {timeout}s: {command_str}",
            returncode=None,
            stdout=stdout,
            stderr=stderr,
        ) from exc
    except OSError as exc:
        raise SSHConnectionError(f"Failed to execute virtctl ssh: {exc}") from exc


def run_ssh_commands(
    vm: VirtualMachineForTests,
    commands: list[str],
    timeout: int | float = TIMEOUT_1MIN,
    check: bool = True,
) -> list[str]:
    """Execute commands on the VM, compatible with pyhelper_utils.run_ssh_commands.

    This is a drop-in replacement for pyhelper_utils.run_ssh_commands.
    It executes commands joined with semicolons.

    Args:
        vm: VirtualMachine object.
        commands: List of commands/arguments to execute.
        timeout: Command timeout in seconds.
        check: If True, raise on non-zero exit code.

    Returns:
        List containing the stdout output as first element.

    Raises:
        SSHCommandError: If check=True and command returns non-zero exit code.
    """
    command_str = " ".join(commands)
    result = run_command(vm=vm, command=command_str, timeout=timeout, check=check)
    return [result.stdout]


def wait_for_ssh_connectivity(
    vm: VirtualMachineForTests,
    timeout: int | float = TIMEOUT_2MIN,
) -> None:
    """Wait for SSH connectivity to the VM.

    Args:
        vm: VirtualMachine object.
        timeout: Maximum time to wait for SSH connectivity.

    Raises:
        TimeoutExpiredError: If SSH is not available within timeout.
    """
    LOGGER.info("Waiting for SSH connectivity", extra={"vm": vm.name, "timeout": timeout})

    for sample in TimeoutSampler(
        wait_timeout=timeout,
        sleep=5,
        func=is_connective,
        vm=vm,
        timeout=30,
    ):
        if sample:
            LOGGER.info("SSH connectivity established", extra={"vm": vm.name})
            return


def is_connective(vm: VirtualMachineForTests, timeout: int | float = 30) -> bool:
    """Check if SSH connection to VM is available.

    Args:
        vm: VirtualMachine object.
        timeout: Connection timeout in seconds.

    Returns:
        True if SSH connection works, False otherwise.
    """
    try:
        result = run_command(vm=vm, command="exit", timeout=timeout, check=False)
        return result.returncode == 0
    except SSHCommandError, SSHConnectionError:
        return False


class OSInfo:
    """OS information accessor for a VM, mimicking rrmngmnt Host.os interface."""

    def __init__(self, vm: VirtualMachineForTests) -> None:
        """Initialize OSInfo.

        Args:
            vm: VirtualMachine object.
        """
        self._vm = vm

    @property
    def release_str(self) -> str:
        """Get the OS release string.

        Returns:
            OS release string (e.g., "Red Hat Enterprise Linux 9.2").
        """
        result = run_command(vm=self._vm, command="cat /etc/os-release", check=True)
        for line in result.stdout.strip().splitlines():
            if line.startswith("PRETTY_NAME="):
                return line.split("=", 1)[1].strip(" \"'")
        return ""

    @property
    def release_info(self) -> dict[str, str]:
        """Get OS release information as dictionary.

        Returns:
            Dictionary with keys like NAME, VERSION, VERSION_ID, PRETTY_NAME, ID.
        """
        result = run_command(vm=self._vm, command="cat /etc/os-release", check=True)
        info: dict[str, str] = {}
        for line in result.stdout.strip().splitlines():
            if "=" in line:
                key, value = line.split("=", 1)
                info[key.strip()] = value.strip(" \"'")
        return info

    @property
    def kernel_info(self) -> KernelInfo:
        """Get kernel information.

        Returns:
            KernelInfo namedtuple with release, version, and type.
        """
        result = run_command(vm=self._vm, command="uname -r -v -s", check=True)
        parts = result.stdout.strip().split(maxsplit=2)
        kernel_type = parts[0] if len(parts) > 0 else ""
        release = parts[1] if len(parts) > 1 else ""
        version = parts[2] if len(parts) > 2 else ""
        return KernelInfo(release=release, version=version, type=kernel_type)

    @property
    def timezone(self) -> TimezoneInfo:
        """Get timezone information.

        Returns:
            TimezoneInfo namedtuple with name and offset.
            The offset is in QEMU guest agent format (seconds / 36).
        """
        result = run_command(vm=self._vm, command="timedatectl show --property=Timezone --value", check=True)
        tz_name = result.stdout.strip()

        offset_result = run_command(vm=self._vm, command="date +%z", check=True)
        offset_str = offset_result.stdout.strip()

        # Parse date +%z format (e.g., "+0530", "-0800") to QEMU guest agent format
        # QEMU returns offset as seconds/36, so we convert and divide by 36
        offset_seconds = _parse_timezone_offset(offset_str=offset_str)
        offset_value = str(offset_seconds // 36)

        return TimezoneInfo(name=tz_name, offset=offset_value)


class NetworkInfo:
    """Network information accessor for a VM, mimicking rrmngmnt Host.network interface."""

    def __init__(self, vm: VirtualMachineForTests) -> None:
        """Initialize NetworkInfo.

        Args:
            vm: VirtualMachine object.
        """
        self._vm = vm

    @property
    def hostname(self) -> str:
        """Get the hostname of the VM.

        Returns:
            Hostname string.
        """
        result = run_command(vm=self._vm, command="hostname", check=True)
        return result.stdout.strip()


class PackageManager:
    """Package manager accessor for a VM, mimicking rrmngmnt Host.package_manager interface."""

    def __init__(self, vm: VirtualMachineForTests) -> None:
        """Initialize PackageManager.

        Args:
            vm: VirtualMachine object.
        """
        self._vm = vm

    def info(self, package: str) -> str:
        """Get package information.

        Args:
            package: Package name.

        Returns:
            Package info string from rpm or dpkg.
        """
        rpm_cmd = f"rpm -qi {shlex.quote(package)}"
        result = run_command(vm=self._vm, command=rpm_cmd, check=False)
        if result.returncode == 0:
            return result.stdout

        dpkg_cmd = f"dpkg -s {shlex.quote(package)}"
        result = run_command(vm=self._vm, command=dpkg_cmd, check=False)
        return result.stdout

    def exist(self, package: str) -> bool:
        """Check if package is installed.

        Args:
            package: Package name.

        Returns:
            True if package is installed.
        """
        rpm_cmd = f"rpm -q {shlex.quote(package)}"
        result = run_command(vm=self._vm, command=rpm_cmd, check=False)
        if result.returncode == 0:
            return True

        dpkg_cmd = f"dpkg -l {shlex.quote(package)}"
        result = run_command(vm=self._vm, command=dpkg_cmd, check=False)
        return result.returncode == 0


class FileSystem:
    """File system accessor for a VM, mimicking rrmngmnt Host.fs interface."""

    def __init__(self, vm: VirtualMachineForTests) -> None:
        """Initialize FileSystem.

        Args:
            vm: VirtualMachine object.
        """
        self._vm = vm

    def transfer(
        self,
        path_src: str,
        target_host: VirtualMachineForTests | FileSystem,
        path_dst: str,
    ) -> None:
        """Transfer file between VMs using virtctl scp.

        Args:
            path_src: Source file path on this VM.
            target_host: Target VM or FileSystem object.
            path_dst: Destination path on target VM.

        Raises:
            SSHCommandError: If transfer fails.
        """
        target_vm = target_host._vm if isinstance(target_host, FileSystem) else target_host

        username, _ = _get_vm_credentials(vm=self._vm)
        target_username, _ = _get_vm_credentials(vm=target_vm)
        ssh_key_path = _get_ssh_key_path() if _should_use_ssh_key(vm=self._vm) else None

        scp_cmd = [
            VIRTCTL,
            "scp",
            "--local-ssh-opts=-o StrictHostKeyChecking=no",
            "--local-ssh-opts=-o UserKnownHostsFile=/dev/null",
            "--local-ssh-opts=-o LogLevel=ERROR",
        ]

        if ssh_key_path:
            scp_cmd.extend(["--identity-file", ssh_key_path])

        scp_cmd.extend([
            f"{username}@vmi/{self._vm.name}.{self._vm.namespace}:{path_src}",
            f"{target_username}@vmi/{target_vm.name}.{target_vm.namespace}:{path_dst}",
        ])

        LOGGER.info(
            "Transferring file via virtctl scp",
            extra={
                "src_vm": self._vm.name,
                "src_path": path_src,
                "dst_vm": target_vm.name,
                "dst_path": path_dst,
            },
        )

        try:
            success, stdout, stderr = shell_run_command(
                command=scp_cmd,
                check=False,
                verify_stderr=False,
                timeout=int(TIMEOUT_2MIN),
            )
            if not success:
                raise SSHCommandError(
                    message=f"File transfer failed: {stderr}",
                    returncode=1,
                    stdout=stdout,
                    stderr=stderr,
                )
        except subprocess.TimeoutExpired as exc:
            raise SSHCommandError(
                message=f"File transfer timed out: {path_src} -> {path_dst}",
            ) from exc

    def upload(self, local_path: str, remote_path: str) -> None:
        """Upload a file from local machine to VM.

        Args:
            local_path: Path to local file.
            remote_path: Destination path on VM.

        Raises:
            SSHCommandError: If upload fails.
        """
        username, _ = _get_vm_credentials(vm=self._vm)
        ssh_key_path = _get_ssh_key_path() if _should_use_ssh_key(vm=self._vm) else None

        scp_cmd = [
            VIRTCTL,
            "scp",
            "--local-ssh-opts=-o StrictHostKeyChecking=no",
            "--local-ssh-opts=-o UserKnownHostsFile=/dev/null",
            "--local-ssh-opts=-o LogLevel=ERROR",
        ]

        if ssh_key_path:
            scp_cmd.extend(["--identity-file", ssh_key_path])

        scp_cmd.extend([
            local_path,
            f"{username}@vmi/{self._vm.name}.{self._vm.namespace}:{remote_path}",
        ])

        LOGGER.info(
            "Uploading file to VM",
            extra={"vm": self._vm.name, "local_path": local_path, "remote_path": remote_path},
        )

        try:
            success, stdout, stderr = shell_run_command(
                command=scp_cmd,
                check=False,
                verify_stderr=False,
                timeout=int(TIMEOUT_2MIN),
            )
            if not success:
                raise SSHCommandError(
                    message=f"File upload failed: {stderr}",
                    returncode=1,
                    stdout=stdout,
                    stderr=stderr,
                )
        except subprocess.TimeoutExpired as exc:
            raise SSHCommandError(
                message=f"File upload timed out: {local_path} -> {remote_path}",
            ) from exc

    def download(self, remote_path: str, local_path: str) -> None:
        """Download a file from VM to local machine.

        Args:
            remote_path: Path to file on VM.
            local_path: Destination path on local machine.

        Raises:
            SSHCommandError: If download fails.
        """
        username, _ = _get_vm_credentials(vm=self._vm)
        ssh_key_path = _get_ssh_key_path() if _should_use_ssh_key(vm=self._vm) else None

        scp_cmd = [
            VIRTCTL,
            "scp",
            "--local-ssh-opts=-o StrictHostKeyChecking=no",
            "--local-ssh-opts=-o UserKnownHostsFile=/dev/null",
            "--local-ssh-opts=-o LogLevel=ERROR",
        ]

        if ssh_key_path:
            scp_cmd.extend(["--identity-file", ssh_key_path])

        scp_cmd.extend([
            f"{username}@vmi/{self._vm.name}.{self._vm.namespace}:{remote_path}",
            local_path,
        ])

        LOGGER.info(
            "Downloading file from VM",
            extra={"vm": self._vm.name, "remote_path": remote_path, "local_path": local_path},
        )

        try:
            success, stdout, stderr = shell_run_command(
                command=scp_cmd,
                check=False,
                verify_stderr=False,
                timeout=int(TIMEOUT_2MIN),
            )
            if not success:
                raise SSHCommandError(
                    message=f"File download failed: {stderr}",
                    returncode=1,
                    stdout=stdout,
                    stderr=stderr,
                )
        except subprocess.TimeoutExpired as exc:
            raise SSHCommandError(
                message=f"File download timed out: {remote_path} -> {local_path}",
            ) from exc


class SSHExecutor:
    """SSH executor for a VM, providing command execution interface."""

    def __init__(self, vm: VirtualMachineForTests) -> None:
        """Initialize SSHExecutor.

        Args:
            vm: VirtualMachine object.
        """
        self._vm = vm

    def run_cmd(
        self,
        command: list[str],
        timeout: int = TIMEOUT_1MIN,
    ) -> tuple[int, str, str]:
        """Run command and return (rc, stdout, stderr).

        Args:
            command: Command as list of arguments.
            timeout: Command timeout in seconds.

        Returns:
            Tuple of (returncode, stdout, stderr).
        """
        result = run_command(vm=self._vm, command=command, timeout=timeout, check=False)
        return result.returncode, result.stdout, result.stderr


class SSHClient:
    """SSH client wrapper for a VM, mimicking rrmngmnt Host interface.

    This class provides a drop-in replacement for the rrmngmnt Host object
    returned by VirtualMachineForTests.ssh_exec property.

    Attributes:
        os: OSInfo accessor for OS-related queries.
        network: NetworkInfo accessor for network-related queries.
        package_manager: PackageManager accessor for package operations.
        fs: FileSystem accessor for file operations.
    """

    def __init__(self, vm: VirtualMachineForTests) -> None:
        """Initialize SSHClient.

        Args:
            vm: VirtualMachine object.
        """
        self._vm = vm
        self.os = OSInfo(vm=vm)
        self.network = NetworkInfo(vm=vm)
        self.package_manager = PackageManager(vm=vm)
        self.fs = FileSystem(vm=vm)
        self.sudo = False

    def run_command(
        self,
        command: list[str],
        tcp_timeout: float = 60.0,
    ) -> tuple[int, str, str]:
        """Execute command on VM, compatible with rrmngmnt Host.run_command.

        Args:
            command: Command as list of arguments.
            tcp_timeout: Command timeout in seconds.

        Returns:
            Tuple of (returncode, stdout, stderr).
        """
        cmd_str = shlex.join(command)
        if self.sudo:
            cmd_str = f"sudo {cmd_str}"

        result = run_command(vm=self._vm, command=cmd_str, timeout=int(tcp_timeout), check=False)
        return result.returncode, result.stdout, result.stderr

    def executor(self) -> SSHExecutor:
        """Get an SSHExecutor for this VM.

        Returns:
            SSHExecutor instance.
        """
        return SSHExecutor(vm=self._vm)


def get_os_release_str(vm: VirtualMachineForTests) -> str:
    """Get the OS release string from a VM.

    Args:
        vm: VirtualMachine object.

    Returns:
        OS release string (e.g., "Red Hat Enterprise Linux 9.2").
    """
    return OSInfo(vm=vm).release_str


def get_os_release_info(vm: VirtualMachineForTests) -> dict[str, str]:
    """Get OS release information from a VM.

    Args:
        vm: VirtualMachine object.

    Returns:
        Dictionary with keys like NAME, VERSION, VERSION_ID, PRETTY_NAME, ID.
    """
    return OSInfo(vm=vm).release_info


def get_kernel_info(vm: VirtualMachineForTests) -> KernelInfo:
    """Get kernel information from a VM.

    Args:
        vm: VirtualMachine object.

    Returns:
        KernelInfo namedtuple with release, version, and type.
    """
    return OSInfo(vm=vm).kernel_info


def get_timezone(vm: VirtualMachineForTests) -> TimezoneInfo:
    """Get timezone information from a VM.

    Args:
        vm: VirtualMachine object.

    Returns:
        TimezoneInfo namedtuple with name and offset.
    """
    return OSInfo(vm=vm).timezone


def get_hostname(vm: VirtualMachineForTests) -> str:
    """Get the hostname of a VM.

    Args:
        vm: VirtualMachine object.

    Returns:
        Hostname string.
    """
    return NetworkInfo(vm=vm).hostname


def get_package_info(vm: VirtualMachineForTests, package_name: str) -> str:
    """Get package information from a VM.

    Args:
        vm: VirtualMachine object.
        package_name: Name of the package.

    Returns:
        Package info string.
    """
    return PackageManager(vm=vm).info(package=package_name)


def transfer_file(
    vm: VirtualMachineForTests,
    src_path: str,
    dst_path: str,
    upload: bool = True,
) -> None:
    """Transfer file to/from VM.

    Args:
        vm: VirtualMachine object.
        src_path: Source file path.
        dst_path: Destination file path.
        upload: If True, upload local file to VM. If False, download from VM.

    Raises:
        SSHCommandError: If transfer fails.
    """
    fs = FileSystem(vm=vm)
    if upload:
        fs.upload(local_path=src_path, remote_path=dst_path)
    else:
        fs.download(remote_path=src_path, local_path=dst_path)


def create_ssh_client(vm: VirtualMachineForTests) -> SSHClient:
    """Create an SSHClient for a VM.

    This is the main entry point for creating an SSH client that can be
    used as a drop-in replacement for the rrmngmnt Host object.

    Args:
        vm: VirtualMachine object.

    Returns:
        SSHClient instance with os, network, package_manager, and fs accessors.
    """
    return SSHClient(vm=vm)
