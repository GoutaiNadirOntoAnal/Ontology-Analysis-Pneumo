def medecin_context(request):
    is_medecin = request.user.groups.filter(name='Medecin').exists() or request.user.is_superuser
    is_superuser = request.user.is_superuser
    return {'is_medecin': is_medecin,'is_superuser':is_superuser}
