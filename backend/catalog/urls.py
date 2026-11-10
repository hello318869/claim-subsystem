from django.urls import path

from catalog import views

urlpatterns = [
    path("meta/campuses", views.CampusListView.as_view()),
    path("meta/categories", views.CategoryListView.as_view()),
    path("meta/locations", views.LocationListView.as_view()),
]
