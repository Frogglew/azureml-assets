# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""This file contains unit tests for minibatch aggregator."""

import datetime

from src.batch_score.root.common.common_enums import AuthenticationType, ApiType, EndpointType
from src.batch_score.root.common.telemetry.minibatch_aggregator import MinibatchAggregator
from src.batch_score.root.common.telemetry.events.batch_score_minibatch_completed_event import (
    BatchScoreMinibatchCompletedEvent
)
from src.batch_score.root.common.telemetry.events.batch_score_minibatch_endpoint_health_event import (
    BatchScoreMinibatchEndpointHealthEvent
)
from src.batch_score.root.common.telemetry.events.batch_score_minibatch_started_event import (
    BatchScoreMinibatchStartedEvent
)
from src.batch_score.root.common.telemetry.events.batch_score_request_completed_event import (
    BatchScoreRequestCompletedEvent
)
from src.batch_score.root.common.telemetry.events.batch_score_input_row_completed_event import (
    BatchScoreInputRowCompletedEvent
)


def test_minibatch_aggregator_summarize(mock_run_context):
    """Test summarize function in minibatch aggregator."""
    # Arrange
    minibatch_aggregator = MinibatchAggregator()

    minibatch_started_datetime = datetime.datetime(2024, 1, 1, 0, 0)
    minibatch_row_count = 100
    failed_row_count = 5

    # Act
    minibatch_aggregator.add(event=BatchScoreMinibatchStartedEvent(
        event_time=minibatch_started_datetime,
        minibatch_id='minibatch_id',
        scoring_url='scoring_url',
        quota_audience='quota_audience',
        input_row_count=minibatch_row_count,
        retry_count=0,
    ))

    # Some requests succeed.
    for i in range(1, 1 + minibatch_row_count - failed_row_count):
        # First request is throttled.
        minibatch_aggregator.add(event=BatchScoreRequestCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=0.5*i),
            minibatch_id='minibatch_id',
            model_name="model_name",
            duration_ms=0.5 * i,
            response_code=429 if i % 2 == 0 else -408,
            prompt_tokens=1000,
            completion_tokens=0,
        ))

        # Second request is successful.
        minibatch_aggregator.add(event=BatchScoreRequestCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=i),
            minibatch_id='minibatch_id',
            model_name="model_name",
            duration_ms=0.5 * i,
            response_code=200,
            prompt_tokens=1000,
            completion_tokens=500,
        ))

        # Sucessful request produces a completed row.
        minibatch_aggregator.add(event=BatchScoreInputRowCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=i),
            minibatch_id='minibatch_id',
            is_successful=True,
            prompt_tokens=1000,
            completion_tokens=500,
            retry_count=1,
            duration_ms=1,
        ))

    # Some requests fail.
    for i in range(1 + minibatch_row_count - failed_row_count, 1 + minibatch_row_count):
        # First request is throttled.
        minibatch_aggregator.add(event=BatchScoreRequestCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=0.5*i),
            minibatch_id='minibatch_id',
            model_name="model_name2",
            duration_ms=0.5 * i,
            response_code=429 if i % 2 == 0 else -408,
            prompt_tokens=1000,
            completion_tokens=0,
        ))

        # Second request fails.
        minibatch_aggregator.add(event=BatchScoreRequestCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=i),
            minibatch_id='minibatch_id',
            model_name="model_name2",
            duration_ms=0.5 * i,
            response_code=500 if i % 2 == 0 else -500,
            prompt_tokens=1000,
            completion_tokens=0,
        ))

        # Failed request produces a completed row.
        minibatch_aggregator.add(event=BatchScoreInputRowCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=i),
            minibatch_id='minibatch_id',
            is_successful=False,
            prompt_tokens=1000,
            completion_tokens=0,
            retry_count=1,
            duration_ms=1,
        ))

    summary = minibatch_aggregator.summarize(
        minibatch_id='minibatch_id',
        end_time=minibatch_started_datetime + datetime.timedelta(milliseconds=1234),
        output_row_count=minibatch_row_count - failed_row_count,
    )

    # Assert
    assert isinstance(summary, BatchScoreMinibatchCompletedEvent)
    _assert_no_numpy_types(summary)

    assert summary.minibatch_id == 'minibatch_id'
    assert summary.scoring_url == 'scoring_url'
    assert summary.quota_audience == 'quota_audience'
    assert summary.model_name == "model_name"  # Only the first model name should be used.
    assert summary.retry_count == 0

    assert summary.total_prompt_tokens == 100 * 1000
    assert summary.total_completion_tokens == 95 * 500

    assert summary.input_row_count == 100
    assert summary.succeeded_row_count == 95
    assert summary.failed_row_count == 5
    assert summary.output_row_count == 95

    assert summary.http_request_count == 200
    assert summary.http_request_succeeded_count == 95
    assert summary.http_request_user_error_count == 100
    assert summary.http_request_system_error_count == 5
    assert summary.http_request_retry_count == 100

    # The first request completes 0.5ms after the start of the minibatch.
    assert round(summary.http_request_duration_p0_ms, 1) == 0.5
    assert round(summary.http_request_duration_p50_ms) == round(50 / 2)
    assert round(summary.http_request_duration_p90_ms) == round(90 / 2)
    assert round(summary.http_request_duration_p95_ms) == round(95 / 2)
    assert round(summary.http_request_duration_p99_ms) == round(99 / 2)
    assert round(summary.http_request_duration_p100_ms) == round(100 / 2)

    # The first row completes 1ms after the start of the minibatch.
    assert round(summary.progress_duration_p0_ms) == 1
    assert round(summary.progress_duration_p50_ms) == 50
    assert round(summary.progress_duration_p90_ms) == 90
    assert round(summary.progress_duration_p95_ms) == 95
    assert round(summary.progress_duration_p99_ms) == 99
    assert round(summary.progress_duration_p100_ms) == 100
    assert round(summary.total_duration_ms) == 1234

    # Act
    minibatch_aggregator.clear(minibatch_id='minibatch_id')
    summary2 = minibatch_aggregator.summarize(
        minibatch_id='minibatch_id',
        end_time=minibatch_started_datetime + datetime.timedelta(milliseconds=1234),
        output_row_count=0,
    )

    # Assert
    assert isinstance(summary2, BatchScoreMinibatchCompletedEvent)

    assert summary2.minibatch_id == 'minibatch_id'
    assert summary2.scoring_url is None
    assert summary2.quota_audience is None
    assert summary2.model_name is None
    assert summary2.retry_count == 0

    assert summary2.total_prompt_tokens == 0
    assert summary2.total_completion_tokens == 0

    assert summary2.input_row_count == 0
    assert summary2.succeeded_row_count == 0
    assert summary2.failed_row_count == 0
    assert summary2.output_row_count == 0

    assert summary2.http_request_count == 0
    assert summary2.http_request_duration_p0_ms == 0
    assert summary2.http_request_duration_p50_ms == 0
    assert summary2.http_request_duration_p90_ms == 0
    assert summary2.http_request_duration_p95_ms == 0
    assert summary2.http_request_duration_p99_ms == 0
    assert summary2.http_request_duration_p100_ms == 0

    assert summary2.progress_duration_p0_ms == 0
    assert summary2.progress_duration_p50_ms == 0
    assert summary2.progress_duration_p90_ms == 0
    assert summary2.progress_duration_p95_ms == 0
    assert summary2.progress_duration_p99_ms == 0
    assert summary2.progress_duration_p100_ms == 0
    assert round(summary2.total_duration_ms) == 0


def test_minibatch_aggregator_summarize_endpoints(mock_run_context):
    """Test summarize_endpoints function in minibatch aggregator."""
    # Arrange
    minibatch_aggregator = MinibatchAggregator()

    minibatch_started_datetime = datetime.datetime(2024, 1, 1, 0, 0)
    minibatch_row_count = 100

    # Endpoint 1
    scoring_url_endpoint1 = "https://endpoint1.centralus.inference.ml.azure.com/"
    minibatch_row_count_endpoint1 = 60

    # Endpoint 2
    scoring_url_endpoint2 = "https://endpoint2.centralus.inference.ml.azure.com/"
    minibatch_request_count_endpoint2 = minibatch_row_count - minibatch_row_count_endpoint1
    failed_request_count_endpoint2 = 5
    succeeded_request_count_endpoint2 = minibatch_request_count_endpoint2 - failed_request_count_endpoint2

    # Act
    minibatch_aggregator.add(event=BatchScoreMinibatchStartedEvent(
        event_time=minibatch_started_datetime,
        minibatch_id='minibatch_id',
        scoring_url='scoring_url',
        quota_audience='quota_audience',
        input_row_count=minibatch_row_count,
        retry_count=0,
    ))

    # Some requests target endpoint 1 only and succeed after retry.
    for i in range(1, 1 + minibatch_row_count_endpoint1):
        # First request is throttled.
        minibatch_aggregator.add(event=BatchScoreRequestCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=0.5*i),
            minibatch_id='minibatch_id',
            scoring_url=scoring_url_endpoint1,
            duration_ms=0.5 * i,
            response_code=429 if i % 2 == 0 else -408,
            prompt_tokens=0,
            completion_tokens=0,
        ))

        # Second request is successful.
        minibatch_aggregator.add(event=BatchScoreRequestCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=i),
            minibatch_id='minibatch_id',
            scoring_url=scoring_url_endpoint1,
            duration_ms=0.5 * i,
            response_code=200,
            prompt_tokens=1000,
            completion_tokens=500,
        ))

        # Sucessful request produces a completed row.
        minibatch_aggregator.add(event=BatchScoreInputRowCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=i),
            minibatch_id='minibatch_id',
            is_successful=True,
            prompt_tokens=1000,
            completion_tokens=500,
            retry_count=1,
        ))

    # Some requests target endpoint 1 but fail then switch to endpoint 2.
    for i in range(1 + minibatch_row_count_endpoint1,
                   1 + minibatch_row_count_endpoint1 + succeeded_request_count_endpoint2):
        # First request to endpoint 1 fails.
        minibatch_aggregator.add(event=BatchScoreRequestCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=0.5*i),
            minibatch_id='minibatch_id',
            scoring_url=scoring_url_endpoint1,
            duration_ms=0.5 * i,
            response_code=429 if i % 2 == 0 else -408,
            prompt_tokens=0,
            completion_tokens=0,
        ))

        # Second request to endpoint 2 succeeds.
        minibatch_aggregator.add(event=BatchScoreRequestCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=i),
            minibatch_id='minibatch_id',
            scoring_url=scoring_url_endpoint2,
            duration_ms=0.5 * i,
            response_code=200,
            prompt_tokens=1000,
            completion_tokens=500,
        ))

        # Failed request produces a completed row.
        minibatch_aggregator.add(event=BatchScoreInputRowCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=i),
            minibatch_id='minibatch_id',
            is_successful=True,
            prompt_tokens=1000,
            completion_tokens=500,
            retry_count=1,
        ))

    # Some requests fail in both endpoint 1 and endpoint 2.
    for i in range(1 + minibatch_row_count_endpoint1 + succeeded_request_count_endpoint2, 1 + minibatch_row_count):
        # First request to endpoint 1 fails.
        minibatch_aggregator.add(event=BatchScoreRequestCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=0.5*i),
            minibatch_id='minibatch_id',
            scoring_url=scoring_url_endpoint1,
            duration_ms=0.5 * i,
            response_code=429 if i % 2 == 0 else -408,
            prompt_tokens=0,
            completion_tokens=0,
        ))

        # Second request to endpoint 2 fails.
        minibatch_aggregator.add(event=BatchScoreRequestCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=i),
            minibatch_id='minibatch_id',
            scoring_url=scoring_url_endpoint2,
            duration_ms=0.5 * i,
            response_code=500 if i % 2 == 0 else -500,
            prompt_tokens=0,
            completion_tokens=0,
        ))

        # Failed request produces a failed row.
        minibatch_aggregator.add(event=BatchScoreInputRowCompletedEvent(
            event_time=minibatch_started_datetime + datetime.timedelta(milliseconds=i),
            minibatch_id='minibatch_id',
            is_successful=False,
            prompt_tokens=0,
            completion_tokens=0,
            retry_count=2,
        ))

    result_events = minibatch_aggregator.summarize_endpoints(minibatch_id='minibatch_id')

    # Assert
    assert all(isinstance(e, BatchScoreMinibatchEndpointHealthEvent) for e in result_events)

    assert len(result_events) == 2
    [_assert_no_numpy_types(e) for e in result_events]

    event1 = result_events[0]
    assert event1.minibatch_id == 'minibatch_id'
    assert event1.scoring_url == scoring_url_endpoint1
    assert event1.quota_audience == 'quota_audience'

    assert event1.http_request_count == 160
    assert event1.http_request_succeeded_count == 60
    assert event1.http_request_user_error_count == 100
    assert event1.http_request_system_error_count == 0

    event2 = result_events[1]
    assert event2.minibatch_id == 'minibatch_id'
    assert event2.scoring_url == scoring_url_endpoint2
    assert event2.quota_audience == 'quota_audience'

    assert event2.http_request_count == 40
    assert event2.http_request_succeeded_count == 35
    assert event2.http_request_user_error_count == 0
    assert event2.http_request_system_error_count == 5

    # Act
    minibatch_aggregator.clear(minibatch_id='minibatch_id')

    result_events2 = minibatch_aggregator.summarize_endpoints(minibatch_id='minibatch_id')

    # Assert
    assert not len(result_events2)


def _assert_no_numpy_types(summary):
    # Confirm that numpy types are not present in the summary object.
    expected_types = [
        ApiType,
        AuthenticationType,
        bool,
        datetime.datetime,
        EndpointType,
        float,
        int,
        str,
        type(None)]
    types = [type(value) for value in summary.to_dictionary().values()]
    assert all(t in expected_types for t in types)
