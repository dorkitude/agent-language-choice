from django.urls import path

from . import views

urlpatterns = [
    path("health", views.health),
    path("v1/dice/stats", views.dice_stats),
    path("v1/checks/ability", views.ability_check),
    path("v1/encounters/adjusted-xp", views.adjusted_xp),
    path("v1/initiative/order", views.initiative_order),
    path("v1/characters/ability-modifier", views.ability_modifier),
    path("v1/characters/proficiency", views.proficiency),
    path("v1/characters/derived-stats", views.derived_stats),
    path("v1/combat/sessions", views.combat_create_session),
    path("v1/combat/sessions/<str:sid>/conditions", views.combat_add_condition),
    path("v1/combat/sessions/<str:sid>/advance", views.combat_advance),
]
