# CNV Utilities Testing TODO

## 🔄 Remaining Work

### Medium Priority - Restore and Fix Removed Test Files (If Required)
The following modules were excluded from coverage but may need testing in the future:

#### data_collector.py (70 statements)
- [ ] Add tests for `collect_alerts_data()` function
- [ ] Add tests for `collect_vnc_screenshot_for_vms()` function
- [ ] Add tests for `collect_ocp_must_gather()` function
- [ ] Add tests for `collect_default_cnv_must_gather_with_vm_gather()` function
- [ ] Fix existing `test_data_collector.py` mocking issues

#### monitoring.py (112 statements)
- [ ] Fix failing tests in `test_monitoring.py`:
  - `TestValidateAlertCnvLabels` - Mock alert structure properly
  - `TestValidateAlerts` - Fix KeyError for 'labels' field
  - `TestWaitForOperatorHealthMetricsValue` - Fix operator health values mapping
  - `TestGetMetricsValue` - Fix empty result handling

#### os_utils.py (54 statements)
- [ ] Fix failing tests in `test_os_utils.py`:
  - `TestGenerateOsMatrixDict` - Fix RHEL and Windows OS matrix generation
  - `TestGenerateInstanceTypeRhelOsMatrix` - Fix instance type matrix tests
  - Address import/dependency issues

#### ssp.py (121 statements)
- [ ] Fix failing tests in `test_ssp.py`:
  - `TestWaitForDeletedDataImportCrons` - Fix timeout and success scenarios
  - `TestWaitForAtLeastOneAutoUpdateDataImportCron` - Fix cron waiting logic

### Lower Priority - Large Complex Modules
These modules require significant testing effort and may be out of scope:

#### hco.py (176 statements) - Partially tested
- [ ] Fix remaining failing tests (13 tests failing)
- [ ] Add tests for untested functions like `get_hco_spec`, `get_hco_version`, etc.

#### infra.py (648 statements)
- [ ] Create comprehensive test suite (currently 0% coverage)
- [ ] Mock Kubernetes/OpenShift client interactions

#### network.py (436 statements)
- [ ] Create comprehensive test suite (currently 0% coverage)
- [ ] Mock network configuration operations

#### operator.py (346 statements)
- [ ] Create comprehensive test suite (currently 0% coverage)
- [ ] Note: Has naming conflict with Python's operator module

#### pytest_utils.py (111 statements)
- [ ] Create comprehensive test suite (currently 0% coverage)
- [ ] Mock pytest configuration and utilities

#### storage.py (478 statements)
- [ ] Create comprehensive test suite (currently 0% coverage)
- [ ] Mock storage operations and configurations

#### virt.py (961 statements)
- [ ] Create comprehensive test suite (currently 0% coverage)
- [ ] Mock virtualization operations - largest module

## 🛠️ Implementation Guidelines

### For Fixing Existing Tests
1. Run individual failing test to see specific error
2. Check the actual function signature and parameters
3. Update mock calls to match expected parameters
4. Verify test logic matches actual implementation

### For New Test Coverage
1. Follow existing test patterns in working test files
2. Use proper mocking to avoid external dependencies
3. Test both success and error scenarios
4. Include edge cases and boundary conditions
5. Use descriptive test names and docstrings

### Test Commands

#### Direct pytest commands (from utilities/ directory):
```bash
# Run specific test file
uv run pytest tests/test_console.py -v

# Run with coverage details
uv run pytest tests/test_console.py --cov=console --cov-report=term-missing
```

#### Tox environment (from project root directory):
```bash
# Run utilities unit tests with coverage verification (90% minimum required)
tox -e utilities-unittests

# List all available tox environments
tox -l
```

#### Coverage Output Formats:
- **Terminal**: Live coverage summary during test execution
- **HTML**: Detailed interactive report at `utilities/htmlcov/index.html`
- **XML**: Machine-readable report for CI/CD integration (`coverage.xml`)
