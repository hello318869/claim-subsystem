from django.urls import path

from posts import views

urlpatterns = [
    path("post-images", views.PostImageUploadView.as_view()),
    path("post-images/<int:pk>/content", views.PostImageContentView.as_view()),
    path("posts", views.PostCollectionView.as_view()),
    path("posts/<str:pk>", views.PostDetailView.as_view()),
    path("posts/<str:pk>/withdraw", views.PostWithdrawView.as_view()),
    path("posts/<str:pk>/restore", views.PostRestoreView.as_view()),
    path("posts/<str:pk>/resolve", views.PostResolveView.as_view()),
    path("posts/<str:pk>/reopen", views.PostReopenView.as_view()),
    path("demo/posts", views.DemoPostsView.as_view(), name="demo-posts"),
]
