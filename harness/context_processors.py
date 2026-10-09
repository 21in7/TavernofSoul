"""Keep ads, consent overlays and external fonts out of isolated harness pages."""


def offline(request):
    return {'harness_offline': True}
