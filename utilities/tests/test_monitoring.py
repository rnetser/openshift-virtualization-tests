"""Unit tests for monitoring module"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from timeout_sampler import TimeoutExpiredError

# Add utilities to Python path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from utilities.monitoring import (
    get_all_firing_alerts,
    get_metrics_value,
    validate_alert_cnv_labels,
    validate_alerts,
    wait_for_alert,
    wait_for_firing_alert_clean_up,
    wait_for_gauge_metrics_value,
    wait_for_operator_health_metrics_value,
)


class TestWaitForAlert:
    """Test cases for wait_for_alert function"""

    @pytest.mark.unit
    @patch("utilities.monitoring.TimeoutSampler")
    def test_wait_for_alert_success(self, mock_sampler_class):
        """Test successful alert waiting"""
        mock_prometheus = MagicMock()
        alert_name = "TestAlert"
        expected_alerts = [{"name": "TestAlert", "state": "firing"}]

        # Mock sampler to return alerts on first iteration
        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([expected_alerts])
        mock_sampler_class.return_value = mock_sampler

        result = wait_for_alert(mock_prometheus, alert_name)

        assert result == expected_alerts
        mock_sampler_class.assert_called_once_with(
            wait_timeout=600,  # TIMEOUT_10MIN
            sleep=5,  # TIMEOUT_5SEC
            func=mock_prometheus.get_all_alerts_by_alert_name,
            alert_name=alert_name,
        )

    @pytest.mark.unit
    @patch("utilities.monitoring.collect_alerts_data")
    @patch("utilities.monitoring.TimeoutSampler")
    def test_wait_for_alert_timeout(self, mock_sampler_class, mock_collect_alerts):
        """Test alert waiting timeout"""
        mock_prometheus = MagicMock()
        alert_name = "TestAlert"

        # Mock sampler to raise TimeoutExpiredError
        mock_sampler = MagicMock()
        mock_sampler.__iter__.side_effect = TimeoutExpiredError("Timeout")
        mock_sampler_class.return_value = mock_sampler

        with pytest.raises(TimeoutExpiredError):
            wait_for_alert(mock_prometheus, alert_name)

        mock_collect_alerts.assert_called_once()


class TestValidateAlertCnvLabels:
    """Test cases for validate_alert_cnv_labels function"""

    @pytest.mark.unit
    def test_validate_alert_cnv_labels_all_match(self):
        """Test when all alert labels match expected values"""
        alerts = [
            {"labels": {"severity": "warning", "namespace": "openshift-cnv"}},
            {"labels": {"severity": "warning", "namespace": "openshift-cnv"}},
        ]
        expected_labels = {"severity": "warning", "namespace": "openshift-cnv"}

        result = validate_alert_cnv_labels(alerts, expected_labels)

        assert result == []

    @pytest.mark.unit
    @patch("utilities.monitoring.LOGGER")
    def test_validate_alert_cnv_labels_mismatch(self, mock_logger):
        """Test when some alert labels don't match"""
        alerts = [
            {"labels": {"severity": "warning", "namespace": "openshift-cnv"}},
            {"labels": {"severity": "critical", "namespace": "openshift-cnv"}},
            {"labels": {"severity": "warning", "namespace": "wrong-namespace"}},
        ]
        expected_labels = {"severity": "warning", "namespace": "openshift-cnv"}

        result = validate_alert_cnv_labels(alerts, expected_labels)

        assert len(result) == 2
        assert result[0]["labels"]["severity"] == "critical"
        assert result[1]["labels"]["namespace"] == "wrong-namespace"

        # Verify error logging
        assert mock_logger.error.call_count == 2

    @pytest.mark.unit
    def test_validate_alert_cnv_labels_empty_alerts(self):
        """Test with empty alerts list"""
        result = validate_alert_cnv_labels([], {"severity": "warning"})
        assert result == []


class TestWaitForFiringAlertCleanUp:
    """Test cases for wait_for_firing_alert_clean_up function"""

    @pytest.mark.unit
    @patch("utilities.monitoring.TimeoutSampler")
    def test_wait_for_firing_alert_clean_up_success(self, mock_sampler_class):
        """Test successful cleanup of firing alerts"""
        mock_prometheus = MagicMock()
        alert_name = "TestAlert"

        # Mock sampler to return no alerts (cleaned up)
        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([None])
        mock_sampler_class.return_value = mock_sampler

        wait_for_firing_alert_clean_up(mock_prometheus, alert_name)

        mock_sampler_class.assert_called_once()

    @pytest.mark.unit
    @patch("utilities.monitoring.TimeoutSampler")
    def test_wait_for_firing_alert_clean_up_with_custom_timeout(self, mock_sampler_class):
        """Test cleanup with custom timeout"""
        mock_prometheus = MagicMock()
        alert_name = "TestAlert"
        custom_timeout = 600

        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([None])
        mock_sampler_class.return_value = mock_sampler

        wait_for_firing_alert_clean_up(mock_prometheus, alert_name, timeout=custom_timeout)

        # Check timeout was passed correctly
        args, kwargs = mock_sampler_class.call_args
        assert kwargs["wait_timeout"] == custom_timeout


class TestValidateAlerts:
    """Test cases for validate_alerts function"""

    @pytest.mark.unit
    def test_validate_alerts_all_expected_found(self):
        """Test when all expected alerts are found"""
        prometheus_alerts = [
            {"labels": {"alertname": "Alert1"}, "state": "firing"},
            {"labels": {"alertname": "Alert2"}, "state": "firing"},
            {"labels": {"alertname": "Alert3"}, "state": "pending"},
        ]
        expected_alerts = ["Alert1", "Alert2"]

        missing, unexpected = validate_alerts(
            prometheus_alerts,
            expected_alerts,
            only_firing=True,
        )

        assert missing == []
        assert unexpected == ["Alert3"]  # Not firing

    @pytest.mark.unit
    def test_validate_alerts_with_missing_alerts(self):
        """Test when some expected alerts are missing"""
        prometheus_alerts = [
            {"labels": {"alertname": "Alert1"}, "state": "firing"},
        ]
        expected_alerts = ["Alert1", "Alert2", "Alert3"]

        missing, unexpected = validate_alerts(
            prometheus_alerts,
            expected_alerts,
            only_firing=True,
        )

        assert set(missing) == {"Alert2", "Alert3"}
        assert unexpected == []

    @pytest.mark.unit
    def test_validate_alerts_include_non_firing(self):
        """Test including non-firing alerts"""
        prometheus_alerts = [
            {"labels": {"alertname": "Alert1"}, "state": "firing"},
            {"labels": {"alertname": "Alert2"}, "state": "pending"},
        ]
        expected_alerts = ["Alert1", "Alert2"]

        missing, unexpected = validate_alerts(
            prometheus_alerts,
            expected_alerts,
            only_firing=False,
        )

        assert missing == []
        assert unexpected == []

    @pytest.mark.unit
    def test_validate_alerts_empty_inputs(self):
        """Test with empty inputs"""
        missing, unexpected = validate_alerts([], [], only_firing=True)
        assert missing == []
        assert unexpected == []


class TestWaitForOperatorHealthMetricsValue:
    """Test cases for wait_for_operator_health_metrics_value function"""

    @pytest.mark.unit
    @patch("utilities.monitoring.get_metrics_value")
    @patch("utilities.monitoring.TimeoutSampler")
    def test_wait_for_operator_health_metrics_success(self, mock_sampler_class, mock_get_metrics):
        """Test successful operator health metrics check"""
        mock_prometheus = MagicMock()
        expected_value = 0
        timeout = 120

        # Mock get_metrics_value to return expected value
        mock_get_metrics.return_value = expected_value

        # Mock sampler
        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([True])
        mock_sampler_class.return_value = mock_sampler

        wait_for_operator_health_metrics_value(
            prometheus=mock_prometheus,
            expected_value=expected_value,
            timeout=timeout,
        )

        mock_get_metrics.assert_called_with(
            mock_prometheus,
            "kubevirt_hyperconverged_operator_health_status",
        )

    @pytest.mark.unit
    @patch("utilities.monitoring.get_metrics_value")
    @patch("utilities.monitoring.TimeoutSampler")
    def test_wait_for_operator_health_metrics_timeout(self, mock_sampler_class, mock_get_metrics):
        """Test operator health metrics timeout"""
        mock_prometheus = MagicMock()
        expected_value = 0

        # Mock get_metrics_value to return wrong value
        mock_get_metrics.return_value = 1

        # Mock sampler to timeout
        mock_sampler = MagicMock()
        mock_sampler.__iter__.side_effect = TimeoutExpiredError("Timeout")
        mock_sampler_class.return_value = mock_sampler

        with pytest.raises(TimeoutExpiredError):
            wait_for_operator_health_metrics_value(
                prometheus=mock_prometheus,
                expected_value=expected_value,
            )


class TestGetAllFiringAlerts:
    """Test cases for get_all_firing_alerts function"""

    @pytest.mark.unit
    def test_get_all_firing_alerts_filters_correctly(self):
        """Test that function filters only firing alerts"""
        mock_prometheus = MagicMock()
        all_alerts = [
            {"state": "firing", "labels": {"alertname": "Alert1"}},
            {"state": "pending", "labels": {"alertname": "Alert2"}},
            {"state": "firing", "labels": {"alertname": "Alert3"}},
            {"state": "inactive", "labels": {"alertname": "Alert4"}},
        ]
        mock_prometheus.get_all_alerts.return_value = all_alerts

        result = get_all_firing_alerts(mock_prometheus)

        assert len(result) == 2
        assert all(alert["state"] == "firing" for alert in result)
        assert result[0]["labels"]["alertname"] == "Alert1"
        assert result[1]["labels"]["alertname"] == "Alert3"

    @pytest.mark.unit
    def test_get_all_firing_alerts_empty(self):
        """Test when no firing alerts exist"""
        mock_prometheus = MagicMock()
        mock_prometheus.get_all_alerts.return_value = []

        result = get_all_firing_alerts(mock_prometheus)

        assert result == []


class TestGetMetricsValue:
    """Test cases for get_metrics_value function"""

    @pytest.mark.unit
    def test_get_metrics_value_single_result(self):
        """Test getting metrics value with single result"""
        mock_prometheus = MagicMock()
        metrics_name = "test_metric"
        expected_value = 42.0

        mock_prometheus.get_instant_metric_value.return_value = [expected_value]

        result = get_metrics_value(mock_prometheus, metrics_name)

        assert result == expected_value
        mock_prometheus.get_instant_metric_value.assert_called_once_with(
            metrics_name=metrics_name,
        )

    @pytest.mark.unit
    def test_get_metrics_value_multiple_results(self):
        """Test getting metrics value with multiple results (returns first)"""
        mock_prometheus = MagicMock()
        metrics_name = "test_metric"

        mock_prometheus.get_instant_metric_value.return_value = [10.0, 20.0, 30.0]

        result = get_metrics_value(mock_prometheus, metrics_name)

        assert result == 10.0

    @pytest.mark.unit
    def test_get_metrics_value_empty_result(self):
        """Test getting metrics value with empty result"""
        mock_prometheus = MagicMock()
        metrics_name = "test_metric"

        mock_prometheus.get_instant_metric_value.return_value = []

        result = get_metrics_value(mock_prometheus, metrics_name)

        assert result is None


class TestWaitForGaugeMetricsValue:
    """Test cases for wait_for_gauge_metrics_value function"""

    @pytest.mark.unit
    @patch("utilities.monitoring.TimeoutSampler")
    def test_wait_for_gauge_metrics_value_success(self, mock_sampler_class):
        """Test successful gauge metrics value wait"""
        mock_prometheus = MagicMock()
        query = "test_gauge_metric"
        expected_value = 100

        # Mock prometheus to return expected value
        mock_prometheus.get_instant_metric_value.return_value = [expected_value]

        # Mock sampler
        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([True])
        mock_sampler_class.return_value = mock_sampler

        wait_for_gauge_metrics_value(mock_prometheus, query, expected_value)

        mock_sampler_class.assert_called_once()

    @pytest.mark.unit
    @patch("utilities.monitoring.TimeoutSampler")
    def test_wait_for_gauge_metrics_value_custom_timeout(self, mock_sampler_class):
        """Test gauge metrics wait with custom timeout"""
        mock_prometheus = MagicMock()
        query = "test_gauge_metric"
        expected_value = 100
        custom_timeout = 600

        mock_prometheus.get_instant_metric_value.return_value = [expected_value]

        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([True])
        mock_sampler_class.return_value = mock_sampler

        wait_for_gauge_metrics_value(
            mock_prometheus,
            query,
            expected_value,
            timeout=custom_timeout,
        )

        # Verify timeout was passed correctly
        args, kwargs = mock_sampler_class.call_args
        assert kwargs["wait_timeout"] == custom_timeout
