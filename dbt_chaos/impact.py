"""Quantify synthetic state divergence, never equate it to actual monetary loss."""
def impact(delta:dict)->dict:
    """Cumulative absolute difference at an observation checkpoint, in synthetic integer cents."""
    keys=sum(len(delta[name]) for name in ("missing","extra","changed"))
    cents=0
    for value in delta["missing"].values():
        cents+=abs(value[1] or 0)
    for value in delta["extra"].values():
        cents+=abs(value[1] or 0)
    for value in delta["changed"].values():
        cents+=abs((value["expected"][1] or 0)-(value["actual"][1] or 0))
    return {"affected_keys":keys,"absolute_cents_exposure":cents}
