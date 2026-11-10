from django.urls import path

from . import views

urlpatterns = [
    path("auth/register", views.RegisterView.as_view()),
    path("auth/login", views.LoginView.as_view()),
    path("auth/logout", views.LogoutView.as_view()),
    path("users/me", views.MeView.as_view()),
    path("users/me/campus-binding", views.CampusBindingView.as_view()),
    path("users/me/posts", views.MyPostsView.as_view()),
]
