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

    def test_validate_alerts_all_expected_found(self):
        """Test when all expected alerts are found"""
        mock_prometheus = MagicMock()
        alert_dict = {"Alert1": "alert1", "Alert2": "alert2"}
        actual_alerts = [
            {"state": "firing", "labels": {"alertname": "Alert1"}},
            {"state": "firing", "labels": {"alertname": "Alert2"}},
            {"state": "pending", "labels": {"alertname": "Alert3"}},
        ]
        mock_prometheus.get_all_alerts.return_value = actual_alerts

        missing, unexpected = validate_alerts(
            mock_prometheus,
            alert_dict,
        )

        assert missing == []
        assert unexpected == []

    def test_validate_alerts_with_missing_alerts(self):
        """Test when some expected alerts are missing"""
        mock_prometheus = MagicMock()
        alert_dict = {"Alert1": "alert1", "Alert2": "alert2", "Alert3": "alert3"}
        actual_alerts = [
            {"state": "firing", "labels": {"alertname": "Alert1"}},
        ]
        mock_prometheus.get_all_alerts.return_value = actual_alerts

        missing, unexpected = validate_alerts(
            mock_prometheus,
            alert_dict,
        )

        assert set(missing) == {"Alert2", "Alert3"}
        assert unexpected == []

    def test_validate_alerts_include_non_firing(self):
        """Test with different state filter"""
        mock_prometheus = MagicMock()
        alert_dict = {"Alert1": "alert1"}
        actual_alerts = [
            {"state": "pending", "labels": {"alertname": "Alert1"}},
            {"state": "firing", "labels": {"alertname": "Alert2"}},
        ]
        mock_prometheus.get_all_alerts.return_value = actual_alerts

        missing, unexpected = validate_alerts(
            mock_prometheus,
            alert_dict,
            state="pending",
        )

        assert missing == []
        assert unexpected == []

    def test_validate_alerts_empty_inputs(self):
        """Test with empty alert dict"""
        mock_prometheus = MagicMock()
        mock_prometheus.get_all_alerts.return_value = []

        missing, unexpected = validate_alerts(mock_prometheus, {})

        assert missing == []
        assert unexpected == []


class TestWaitForOperatorHealthMetricsValue:
    """Test cases for wait_for_operator_health_metrics_value function"""

    @patch("monitoring.TimeoutSampler")
    @patch("monitoring.get_metrics_value")
    def test_wait_for_operator_health_metrics_success(
        self,
        mock_get_metrics,
        mock_sampler_class,
    ):
        """Test successful operator health metrics check"""
        mock_prometheus = MagicMock()
        health_impact_value = 0

        # Mock get_metrics_value to return expected value
        mock_get_metrics.return_value = health_impact_value

        # Mock sampler
        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([True])
        mock_sampler_class.return_value = mock_sampler

        wait_for_operator_health_metrics_value(
            mock_prometheus,
            health_impact_value,
        )

        mock_sampler_class.assert_called_once()
        mock_get_metrics.assert_called()

    @patch("monitoring.TimeoutSampler")
    @patch("monitoring.get_metrics_value")
    def test_wait_for_operator_health_metrics_timeout(
        self,
        mock_get_metrics,
        mock_sampler_class,
    ):
        """Test operator health metrics timeout"""
        mock_prometheus = MagicMock()
        health_impact_value = 0

        # Mock get_metrics_value to return different value
        mock_get_metrics.return_value = 1

        # Mock sampler to timeout
        mock_sampler = MagicMock()
        mock_sampler.__iter__.side_effect = TimeoutExpiredError("Timeout")
        mock_sampler_class.return_value = mock_sampler

        with pytest.raises(TimeoutExpiredError):
            wait_for_operator_health_metrics_value(
                mock_prometheus,
                health_impact_value,
            )


class TestGetAllFiringAlerts:
    """Test cases for get_all_firing_alerts function"""

    def test_get_all_firing_alerts_filters_correctly(self):
        """Test that function filters only firing alerts"""
        mock_prometheus = MagicMock()
        all_alerts = [
            {"state": "firing", "labels": {"alertname": "Alert1", "operator_health_impact": "critical"}},
            {"state": "pending", "labels": {"alertname": "Alert2"}},
            {"state": "firing", "labels": {"alertname": "Alert3", "operator_health_impact": "warning"}},
        ]
        mock_prometheus.alerts.return_value = {"data": {"alerts": all_alerts}}

        result = get_all_firing_alerts(mock_prometheus)

        # Result should be a dict grouped by health impact values
        assert isinstance(result, dict)
        # Check that pending alerts are not included
        all_alerts_in_result = []
        for alerts_list in result.values():
            all_alerts_in_result.extend(alerts_list)
        assert len(all_alerts_in_result) == 2

    def test_get_all_firing_alerts_empty(self):
        """Test when no firing alerts exist"""
        mock_prometheus = MagicMock()
        mock_prometheus.alerts.return_value = {"data": {"alerts": []}}

        result = get_all_firing_alerts(mock_prometheus)

        assert result == {}


class TestGetMetricsValue:
    """Test cases for get_metrics_value function"""

    def test_get_metrics_value_single_result(self):
        """Test getting metrics value with single result"""
        mock_prometheus = MagicMock()
        metrics_name = "test_metric"
        expected_value = 42.0

        mock_prometheus.query.return_value = {
            "data": {
                "result": [
                    {"value": [1234567890, expected_value]},
                ],
            },
        }

        result = get_metrics_value(mock_prometheus, metrics_name)

        assert result == expected_value
        mock_prometheus.query.assert_called_once_with(query=metrics_name)

    def test_get_metrics_value_multiple_results(self):
        """Test getting metrics value with multiple results (returns first)"""
        mock_prometheus = MagicMock()
        metrics_name = "test_metric"

        mock_prometheus.query.return_value = {
            "data": {
                "result": [
                    {"value": [1234567890, 42.0]},
                    {"value": [1234567891, 43.0]},
                ],
            },
        }

        result = get_metrics_value(mock_prometheus, metrics_name)

        assert result == 42.0

    def test_get_metrics_value_empty_result(self):
        """Test getting metrics value with empty result"""
        mock_prometheus = MagicMock()
        metrics_name = "test_metric"

        mock_prometheus.query.return_value = {"data": {"result": []}}

        result = get_metrics_value(mock_prometheus, metrics_name)

        assert result is None


class TestWaitForGaugeMetricsValue:
    """Test cases for wait_for_gauge_metrics_value function"""

    @patch("monitoring.TimeoutSampler")
    def test_wait_for_gauge_metrics_value_success(self, mock_sampler_class):
        """Test successful gauge metrics value wait"""
        mock_prometheus = MagicMock()
        query = "test_gauge_metric"
        expected_value = 100

        # Mock prometheus query to return expected value
        mock_prometheus.query.return_value = {
            "data": {
                "result": [
                    {"value": [1234567890, expected_value]},
                ],
            },
        }

        # Mock sampler
        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([mock_prometheus.query.return_value])
        mock_sampler_class.return_value = mock_sampler

        wait_for_gauge_metrics_value(mock_prometheus, query, expected_value)

        mock_sampler_class.assert_called_once()

    @patch("monitoring.TimeoutSampler")
    def test_wait_for_gauge_metrics_value_custom_timeout(self, mock_sampler_class):
        """Test gauge metrics wait with custom timeout"""
        mock_prometheus = MagicMock()
        query = "test_gauge_metric"
        expected_value = 100
        custom_timeout = 600

        mock_prometheus.query.return_value = {
            "data": {
                "result": [
                    {"value": [1234567890, expected_value]},
                ],
            },
        }

        mock_sampler = MagicMock()
        mock_sampler.__iter__.return_value = iter([mock_prometheus.query.return_value])
        mock_sampler_class.return_value = mock_sampler

        wait_for_gauge_metrics_value(
            mock_prometheus,
            query,
            expected_value,
            timeout=custom_timeout,
        )

        # Verify timeout was passed to sampler
        args, kwargs = mock_sampler_class.call_args
        assert kwargs["timeout"] == custom_timeout
