import datetime
import pendulum
import pytest

from prefect.orion.orchestration.rules import TERMINAL_STATES
from prefect.orion.orchestration.global_policy import (
    SetRunStateType,
    SetStartTime,
    SetEndTime,
    IncrementRunCount,
    IncrementRunTime,
    SetExpectedStartTime,
    SetNextScheduledStartTime,
)
from prefect.orion.schemas import states


@pytest.mark.parametrize("run_type", ["task", "flow"])
class TestGlobalPolicyRules:
    @pytest.mark.parametrize("proposed_state_type", list(states.StateType))
    async def test_rule_updates_run_state(
        self, session, run_type, initialize_orchestration, proposed_state_type
    ):
        initial_state_type = None
        intended_transition = (initial_state_type, proposed_state_type)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
        )

        async with SetRunStateType(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        run = ctx.run
        assert run.state_type == proposed_state_type

    async def test_rule_sets_scheduled_time(
        self,
        session,
        run_type,
        initialize_orchestration,
    ):
        initial_state_type = None
        proposed_state_type = states.StateType.SCHEDULED
        intended_transition = (initial_state_type, proposed_state_type)
        scheduled_time = pendulum.now().add(seconds=42)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
            proposed_details={"scheduled_time": scheduled_time},
        )

        run = ctx.run
        assert run.start_time is None

        async with SetNextScheduledStartTime(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.next_scheduled_start_time == scheduled_time
        assert run.start_time is None

    async def test_rule_removes_scheduled_time_when_exiting_scheduled_state(
        self,
        session,
        run_type,
        initialize_orchestration,
    ):
        initial_state_type = states.StateType.SCHEDULED
        proposed_state_type = states.StateType.PENDING
        intended_transition = (initial_state_type, proposed_state_type)
        scheduled_time = pendulum.now().add(seconds=42)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
            initial_details={"scheduled_time": scheduled_time},
        )

        run = ctx.run
        assert run.start_time is None
        assert run.next_scheduled_start_time is not None

        async with SetNextScheduledStartTime(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.next_scheduled_start_time is None
        assert run.start_time is None

    @pytest.mark.parametrize(
        "non_scheduled_state_type",
        [
            states.StateType.PENDING,
            states.StateType.RUNNING,
            states.StateType.COMPLETED,
        ],
    )
    async def test_rule_sets_expected_start_time_from_non_scheduled(
        self, session, run_type, initialize_orchestration, non_scheduled_state_type
    ):
        initial_state_type = None
        proposed_state_type = non_scheduled_state_type
        intended_transition = (initial_state_type, proposed_state_type)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
        )

        run = ctx.run
        assert run.expected_start_time is None

        async with SetExpectedStartTime(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.expected_start_time == ctx.proposed_state.timestamp
        assert run.start_time is None

    async def test_rule_sets_expected_start_time_from_scheduled(
        self,
        session,
        run_type,
        initialize_orchestration,
    ):
        dt = pendulum.now().add(days=10)

        initial_state_type = None
        proposed_state_type = states.StateType.SCHEDULED
        intended_transition = (initial_state_type, proposed_state_type)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
            proposed_details=dict(scheduled_time=dt),
        )

        run = ctx.run
        assert run.expected_start_time is None

        async with SetExpectedStartTime(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.expected_start_time == dt
        assert run.start_time is None

    async def test_rule_sets_start_time_when_starting_to_run(
        self,
        session,
        run_type,
        initialize_orchestration,
    ):
        initial_state_type = states.StateType.PENDING
        proposed_state_type = states.StateType.RUNNING
        intended_transition = (initial_state_type, proposed_state_type)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
        )

        run = ctx.run
        assert run.start_time is None

        async with SetStartTime(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.start_time is not None

    async def test_rule_updates_run_count_when_starting_to_run(
        self,
        session,
        run_type,
        initialize_orchestration,
    ):
        initial_state_type = states.StateType.PENDING
        proposed_state_type = states.StateType.RUNNING
        intended_transition = (initial_state_type, proposed_state_type)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
        )

        run = ctx.run
        assert run.run_count == 0

        async with IncrementRunCount(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.run_count == 1

    async def test_rule_increments_run_count(
        self,
        session,
        run_type,
        initialize_orchestration,
    ):
        initial_state_type = states.StateType.PENDING
        proposed_state_type = states.StateType.RUNNING
        intended_transition = (initial_state_type, proposed_state_type)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
        )

        run = ctx.run
        run.run_count = 41

        async with IncrementRunCount(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.run_count == 42

    async def test_rule_updates_run_time_after_running(
        self,
        session,
        run_type,
        initialize_orchestration,
    ):
        initial_state_type = states.StateType.RUNNING
        proposed_state_type = states.StateType.COMPLETED
        intended_transition = (initial_state_type, proposed_state_type)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
        )

        now = pendulum.now()
        run = ctx.run
        run.start_time = now.subtract(seconds=42)
        ctx.initial_state.timestamp = now.subtract(seconds=42)
        ctx.proposed_state.timestamp = now
        await session.commit()
        assert run.total_run_time == datetime.timedelta(0)

        async with IncrementRunTime(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.total_run_time == datetime.timedelta(seconds=42)

    async def test_rule_doesnt_update_run_time_when_not_running(
        self,
        session,
        run_type,
        initialize_orchestration,
    ):
        initial_state_type = states.StateType.PENDING
        proposed_state_type = states.StateType.COMPLETED
        intended_transition = (initial_state_type, proposed_state_type)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
        )

        now = pendulum.now()
        run = ctx.run
        run.start_time = now.subtract(seconds=42)
        ctx.initial_state.timestamp = now.subtract(seconds=42)
        ctx.proposed_state.timestamp = now
        await session.commit()
        await session.refresh(run)
        assert run.total_run_time == datetime.timedelta(0)

        async with IncrementRunTime(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.total_run_time == datetime.timedelta(0)

    @pytest.mark.parametrize("proposed_state_type", TERMINAL_STATES)
    async def test_rule_sets_end_time_when_when_run_ends(
        self, session, run_type, initialize_orchestration, proposed_state_type
    ):
        initial_state_type = states.StateType.RUNNING
        intended_transition = (initial_state_type, proposed_state_type)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
        )

        run = ctx.run
        run.start_time = pendulum.now().subtract(seconds=42)
        assert run.end_time is None

        async with SetEndTime(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.end_time is not None

    @pytest.mark.parametrize("initial_state_type", TERMINAL_STATES)
    async def test_rule_unsets_end_time_when_forced_out_of_terminal_state(
        self, session, run_type, initialize_orchestration, initial_state_type
    ):
        proposed_state_type = states.StateType.RUNNING
        intended_transition = (initial_state_type, proposed_state_type)
        ctx = await initialize_orchestration(
            session,
            run_type,
            *intended_transition,
        )

        run = ctx.run
        run.start_time = pendulum.now().subtract(seconds=42)
        run.end_time = pendulum.now()
        assert run.end_time is not None

        async with SetEndTime(ctx, *intended_transition) as ctx:
            await ctx.validate_proposed_state()

        assert run.end_time is None
