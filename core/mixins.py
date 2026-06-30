"""
Shared view mixins.
"""
from django.shortcuts import redirect


class PersistedFilterMixin:
    """
    Persists list-view filters (querystring) in the session so they survive
    navigation away and back (e.g. opening a detail page and clicking
    "Voltar", or clicking a plain nav link), without requiring the link to
    carry the querystring itself.

    Behavior:
    - Request with `?limpar=1`: clears the saved filters and redirects to
      the bare list URL.
    - Request with any other querystring: saves it to the session as-is.
    - Request with no querystring at all: restores the last saved
      querystring from the session (if any) via redirect.

    Subclasses must set `session_key` to a unique string per list view.
    """
    session_key = None

    def get(self, request, *args, **kwargs):
        assert self.session_key, 'PersistedFilterMixin requires session_key to be set.'

        if request.GET.get('limpar'):
            request.session.pop(self.session_key, None)
            return redirect(request.path)

        if request.GET:
            request.session[self.session_key] = request.GET.urlencode()
            return super().get(request, *args, **kwargs)

        querystring_salva = request.session.get(self.session_key)
        if querystring_salva:
            return redirect(f'{request.path}?{querystring_salva}')

        return super().get(request, *args, **kwargs)
