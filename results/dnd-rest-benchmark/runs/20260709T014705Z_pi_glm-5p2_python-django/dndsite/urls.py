from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health),
    path("v1/dice/stats", views.dice_stats),
    path("v1/checks/ability", views.ability_check),
    path("v1/encounters/adjusted-xp", views.adjusted_xp),
    path("v1/initiative/order", views.initiative_order),
]
