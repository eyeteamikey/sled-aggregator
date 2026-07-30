from sled_aggregator.domain.enums import RetrievalState


class InvalidRetrievalTransition(ValueError):
    pass


ALLOWED_TRANSITIONS: dict[RetrievalState, frozenset[RetrievalState]] = {
    RetrievalState.DISCOVERED: frozenset({RetrievalState.ELIGIBLE, RetrievalState.INELIGIBLE}),
    RetrievalState.ELIGIBLE: frozenset({RetrievalState.QUEUED}),
    RetrievalState.QUEUED: frozenset({RetrievalState.LEASED, RetrievalState.CANCELED}),
    RetrievalState.LEASED: frozenset({RetrievalState.QUEUED, RetrievalState.DOWNLOADING}),
    RetrievalState.DOWNLOADING: frozenset({
        RetrievalState.DOWNLOADED, RetrievalState.UNCHANGED, RetrievalState.RESTRICTED,
        RetrievalState.LOGIN_REQUIRED, RetrievalState.REGISTRATION_REQUIRED,
        RetrievalState.CAPTCHA, RetrievalState.NOT_FOUND, RetrievalState.FAILED,
    }),
    RetrievalState.DOWNLOADED: frozenset({RetrievalState.SUPERSEDED}),
    RetrievalState.FAILED: frozenset({RetrievalState.QUEUED}),
}
_QUARANTINABLE = frozenset({
    RetrievalState.DISCOVERED, RetrievalState.ELIGIBLE, RetrievalState.QUEUED,
    RetrievalState.LEASED, RetrievalState.DOWNLOADING, RetrievalState.FAILED,
})
TERMINAL_STATES = frozenset({
    RetrievalState.INELIGIBLE, RetrievalState.UNCHANGED, RetrievalState.SUPERSEDED,
    RetrievalState.RESTRICTED, RetrievalState.LOGIN_REQUIRED,
    RetrievalState.REGISTRATION_REQUIRED, RetrievalState.CAPTCHA, RetrievalState.NOT_FOUND,
    RetrievalState.QUARANTINED, RetrievalState.CANCELED,
})
RETRYABLE_STATES = frozenset({RetrievalState.FAILED, RetrievalState.QUEUED})


def transition(current: RetrievalState, target: RetrievalState) -> RetrievalState:
    permitted = target in ALLOWED_TRANSITIONS.get(current, ())
    if target is RetrievalState.QUARANTINED and current in _QUARANTINABLE:
        permitted = True
    if not permitted:
        raise InvalidRetrievalTransition(f"cannot transition {current.value} to {target.value}")
    return target
