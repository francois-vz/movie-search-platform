using Microsoft.Extensions.DependencyInjection;
using MovieSearch.Application.Movies;

namespace MovieSearch.Application;

public static class DependencyInjection
{
    public static IServiceCollection AddMovieSearchApplication(this IServiceCollection services)
    {
        services.AddMemoryCache();
        services.AddScoped<SearchMovies>();
        services.AddScoped<GetMovieById>();
        services.AddScoped<GetSimilarMovies>();
        services.AddScoped<ListGenres>();
        services.AddScoped<GetDatasetStats>();
        return services;
    }
}
