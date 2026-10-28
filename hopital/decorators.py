from django.contrib.auth.decorators import user_passes_test

def medecin_required(function):
    actual_decorator = user_passes_test(
        lambda user: user.groups.filter(name='Medecin').exists() or user.is_superuser
    )
    return actual_decorator(function)
def superuser_required(function):
    actual_decorator = user_passes_test(
        lambda user:  user.is_superuser
    )
    return actual_decorator(function)