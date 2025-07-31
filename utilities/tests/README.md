# Utilities Unit Tests

This directory contains independent unit tests for the utilities module of the OpenShift Virtualization Tests project.

## Overview

The test suite is designed to be completely independent from the main project's test configuration, allowing for isolated testing of utility functions with their own dependencies and pytest configuration.

## Structure

Tests are organized to mirror the utilities module structure:
```
utilities/tests/
├── __init__.py
├── conftest.py          # Common fixtures and mocks
├── pytest.ini           # Independent pytest configuration
├── test_architecture.py
├── test_bitwarden.py
├── test_console.py
├── test_constants.py
├── test_database.py
├── test_data_collector.py
├── test_exceptions.py
├── test_hco.py          # ✓ Completed (Medium Priority)
├── test_infra.py
├── test_logger.py       # ✓ Completed (Medium Priority)
├── test_monitoring.py   # ✓ Completed (Medium Priority)
├── test_must_gather.py
├── test_network.py
├── test_operator.py
├── test_os_utils.py     # ✓ Completed (Medium Priority)
├── test_pytest_matrix_utils.py
├── test_pytest_utils.py
├── test_ssp.py          # ✓ Completed (Medium Priority)
├── test_storage.py
├── test_virt.py
└── test_vnc_utils.py
```

## Priority Classification

### High Priority (Core functionality)
- [ ] test_architecture.py - Architecture detection utilities
- [ ] test_constants.py - Project constants
- [ ] test_exceptions.py - Custom exceptions
- [ ] test_pytest_utils.py, test_pytest_matrix_utils.py - Testing framework utilities

### Medium Priority (Key features)
- [x] test_logger.py - Logging utilities **✅ COMPLETED - 100% coverage**
- [x] test_os_utils.py - OS-specific utilities **✅ COMPLETED - 70.37% coverage**
- [x] test_monitoring.py - Prometheus monitoring utilities **✅ COMPLETED - Tests need fixes**
- [x] test_hco.py - HyperConverged Operator utilities **✅ COMPLETED - Tests need fixes**
- [x] test_ssp.py - SSP (Scheduling, Scale and Performance) utilities **✅ COMPLETED - Tests need fixes**

### Low Priority (Supporting features)
- [x] test_architecture.py - Architecture detection utilities **✅ CREATED - 6 tests, 5 passing**
- [x] test_bitwarden.py - Secrets management utilities **✅ CREATED - 5 tests, needs fixes**
- [x] test_console.py - Console/SSH interaction utilities **✅ CREATED - 9 tests, 3 passing**
- [x] test_constants.py - Project constants **✅ CREATED - 15 tests, 6 passing**
- [x] test_database.py - Database utilities **✅ CREATED - 8 tests, 2 passing**
- [ ] test_data_collector.py - Data collection utilities
- [ ] test_exceptions.py - Custom exceptions
- [ ] test_infra.py - Infrastructure utilities
- [ ] test_must_gather.py - Must-gather utilities
- [ ] test_network.py - Network utilities
- [ ] test_operator.py - Operator utilities
- [ ] test_pytest_utils.py, test_pytest_matrix_utils.py - Testing framework utilities
- [ ] test_storage.py - Storage utilities
- [ ] test_virt.py - Virtualization utilities
- [ ] test_vnc_utils.py - VNC utilities

## Current Status

### Completed Work
1. ✅ Created independent test infrastructure with:
   - `pytest.ini` - Independent pytest configuration
   - `conftest.py` - Common fixtures and mocks
   - `pyproject.toml` - Dependencies and test configuration
   - `Makefile` - Test execution commands with targets for medium and low priority tests
   - `README.md` - Documentation

2. ✅ Created medium priority tests:
   - `test_logger.py` - **Passing with 100% coverage**
   - `test_os_utils.py` - Partially passing (70.37% coverage)
   - `test_monitoring.py` - Created, needs fixes
   - `test_hco.py` - Created, needs fixes
   - `test_ssp.py` - Created, needs fixes

3. ✅ Created low priority tests:
   - `test_architecture.py` - 6 tests, 5 passing
   - `test_bitwarden.py` - 5 tests, needs fixes
   - `test_console.py` - 9 tests, 3 passing
   - `test_constants.py` - 15 tests, 6 passing
   - `test_database.py` - 8 tests, 2 passing

4. ✅ Fixed import issues:
   - Set `OPENSHIFT_VIRTUALIZATION_TEST_IMAGES_ARCH` environment variable
   - Mocked circular import dependencies
   - Created proper test isolation
   - Added required dependencies (sqlalchemy, pexpect)

### Test Summary
- **Total tests created**: 121 tests across 10 modules
- **Passing tests**: ~46 tests
- **Test coverage**: Varies by module (logger at 100%, others need improvement)

### Known Issues

1. **Logger Issues**: Some tests fail due to logger handler level comparisons with MagicMock
2. **Function Signatures**: Some functions have different signatures than expected in tests
3. **Missing Attributes**: Some mocked objects are missing required attributes
4. **Import Structure**: Complex circular dependencies between modules need refactoring

### Next Steps

To fix the failing tests:
1. Fix logger-related issues by properly mocking the logger
2. Update test expectations to match actual function signatures
3. Add missing attributes to mocked objects
4. Consider refactoring to reduce circular dependencies

To continue with remaining tests:
1. Implement high priority tests (architecture, constants, exceptions, pytest utils)
2. Implement remaining low priority tests
3. Achieve 80% coverage target across all modules

## Running Tests

### Prerequisites
```bash
cd utilities
uv sync --extra test
```

### Using Make (Recommended)
```bash
# Run all tests
make test

# Run with coverage
make test-cov

# Run medium priority tests
make test-medium

# Run specific test file
make test-single TEST=test_architecture.py

# Run in parallel
make test-parallel
```

### Using uv directly
```bash
# Run all tests
uv run pytest tests/

# Run with coverage
uv run pytest tests/ --cov=. --cov-report=html

# Run specific test
uv run pytest tests/test_logger.py -v

# Run with markers
uv run pytest tests/ -m unit
```

### Using pytest directly
```bash
cd utilities/tests

# Run all tests
pytest

# Run with verbose output
pytest -vv

# Run specific test class
pytest test_logger.py::TestDuplicateFilter

# Run specific test method
pytest test_logger.py::TestDuplicateFilter::test_first_log_passes_through
```

## Writing Tests

### Test Structure
```python
class TestModuleName:
    """Test cases for module_name.py functions"""

    @pytest.fixture
    def setup_data(self):
        """Setup test data"""
        return {"key": "value"}

    @pytest.mark.unit
    def test_function_success(self, setup_data):
        """Test successful execution"""
        # Arrange
        input_data = setup_data

        # Act
        result = function_under_test(input_data)

        # Assert
        assert result == expected_value

    @pytest.mark.unit
    def test_function_error(self):
        """Test error handling"""
        with pytest.raises(ExpectedException):
            function_under_test(invalid_input)
```

### Mocking Guidelines

1. **Mock all external dependencies**
   ```python
   @patch('module.external_function')
   def test_with_mock(self, mock_external):
       mock_external.return_value = "mocked"
       result = function_under_test()
       assert result == "expected"
   ```

2. **Use fixtures from conftest.py**
   ```python
   def test_with_fixtures(self, mock_k8s_client, mock_vm):
       # Use pre-configured mocks
       result = process_vm(mock_vm, mock_k8s_client)
       assert result.status == "processed"
   ```

3. **Mock K8s/OpenShift resources**
   ```python
   def test_k8s_operation(self, mock_get_client):
       # mock_get_client is auto-applied to all tests
       resource = SomeResource()
       assert resource.client == mock_get_client.return_value
   ```

## Test Markers

- `@pytest.mark.unit` - Pure unit tests with no external dependencies

## Coverage Requirements

- **Minimum**: 80% code coverage
- **Target**: 90%+ for critical modules
- **Focus Areas**:
  - Business logic
  - Error handling
  - Edge cases
  - Public APIs

### Viewing Coverage Reports
```bash
# Generate HTML report
make test-cov

# Open in browser
open htmlcov/index.html
```

## Debugging Tests

### Verbose Output
```bash
pytest -vv test_logger.py
```

### Show Print Statements
```bash
pytest -s test_monitoring.py
```

### Drop into Debugger
```bash
pytest --pdb test_hco.py
```

### Run Specific Tests
```bash
# Run tests matching pattern
pytest -k "test_wait_for"

# Run tests in specific class
pytest test_ssp.py::TestWaitForSspConditions
```

## Common Patterns

### Testing Timeout Functions
```python
@patch('module.TimeoutSampler')
def test_wait_function(self, mock_sampler_class):
    # Mock successful wait
    mock_sampler = Mock()
    mock_sampler.__iter__.return_value = iter([expected_result])
    mock_sampler_class.return_value = mock_sampler

    result = wait_for_something()
    assert result == expected_result
```

### Testing Resource Operations
```python
@patch('module.ResourceClass')
def test_resource_operation(self, mock_resource_class):
    mock_instance = Mock()
    mock_resource_class.return_value = mock_instance

    result = create_resource("name", "namespace")

    mock_resource_class.assert_called_once_with(
        name="name",
        namespace="namespace"
    )
```

## Best Practices

1. **Keep tests isolated** - Each test should be independent
2. **Use descriptive names** - Test names should explain what they test
3. **Follow AAA pattern** - Arrange, Act, Assert
4. **Mock external dependencies** - Don't make real API calls
5. **Test edge cases** - Empty lists, None values, exceptions
6. **Keep tests fast** - Mark slow tests appropriately
7. **Use fixtures wisely** - Reuse common setup code

## Continuous Integration

Tests are automatically run on:
- Pull requests
- Commits to main branch
- Nightly builds

Failed tests will block merging until fixed.

## Contributing

1. Add tests for any new utility functions
2. Update existing tests when modifying functions
3. Ensure 80% coverage is maintained
4. Run `make lint` before committing
5. Update this README if adding new test patterns
