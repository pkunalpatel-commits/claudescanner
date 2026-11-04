"""Dynamic ATM +/- N selection. Strike lists come from the instrument master, so each stock keeps
its own strike interval; ATM is found by nearest strike to the live underlying LTP."""


def strike_interval(strikes):
    d = [b - a for a, b in zip(strikes, strikes[1:]) if b > a]
    return min(d) if d else None


def atm_index(strikes, price):
    return min(range(len(strikes)), key=lambda i: abs(strikes[i] - price))


def select_strikes(strikes, price, n_ce, n_pe):
    """Returns {"atm": strike, "CE": [(strike, dist)], "PE": [...]}; dist = strikes away from ATM
    (2N+1 strikes per side when the chain is wide enough). CE and PE ranges are independent."""
    if not strikes: return {"atm": None, "CE": [], "PE": []}
    i = atm_index(strikes, price)
    rng = lambda n: [(strikes[j], j - i) for j in range(max(0, i - n), min(len(strikes), i + n + 1))]
    return {"atm": strikes[i], "CE": rng(max(0, int(n_ce))), "PE": rng(max(0, int(n_pe)))}
