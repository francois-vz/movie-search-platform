using System.IdentityModel.Tokens.Jwt;
using System.Text;
using System.Threading.RateLimiting;
using Microsoft.AspNetCore.Authentication.JwtBearer;
using Microsoft.AspNetCore.Http.Timeouts;
using Microsoft.AspNetCore.Mvc;
using Microsoft.IdentityModel.Tokens;
using MovieSearch.Api.Auth;
using MovieSearch.Api.Configuration;
using MovieSearch.Api.Endpoints;
using MovieSearch.Application;
using MovieSearch.Application.Caching;
using MovieSearch.Domain;
using MovieSearch.Infrastructure.Fake;
using MovieSearch.Infrastructure.Mcp;
using OpenTelemetry.Metrics;
using OpenTelemetry.Resources;
using OpenTelemetry.Trace;

namespace MovieSearch.Api.Hosting;

public static class ServiceCollectionExtensions
{
    public static IServiceCollection AddMovieSearchApi(
        this IServiceCollection services,
        MovieSearchApiOptions options,
        IHostEnvironment environment)
    {
        services.AddSingleton(options);
        services.AddSingleton<TokenService>();
        services.AddMovieSearchApplication();
        services.AddMovieSearchClient(options, environment);
        services.AddMovieSearchAuth(options);
        services.AddMovieSearchRateLimiting(options);
        services.AddRequestTimeouts(timeout =>
        {
            timeout.DefaultPolicy = new RequestTimeoutPolicy
            {
                Timeout = TimeSpan.FromSeconds(options.RequestTimeoutSeconds),
            };
        });
        services.AddProblemDetails();
        return services;
    }

    public static IServiceCollection AddMovieSearchClient(
        this IServiceCollection services,
        MovieSearchApiOptions options,
        IHostEnvironment environment)
    {
        var useFake = options.UseFakeMcp || environment.IsEnvironment("Testing");
        if (useFake)
        {
            services.AddSingleton<FakeMovieSearchClient>();
            services.AddSingleton<IMovieSearchClient>(sp => new CachingMovieSearchClient(
                sp.GetRequiredService<FakeMovieSearchClient>(),
                sp.GetRequiredService<Microsoft.Extensions.Caching.Memory.IMemoryCache>(),
                TimeSpan.FromSeconds(options.CacheTtlSeconds)));
        }
        else
        {
            services.AddSingleton(sp => new McpMovieSearchClient(
                options.McpServerUrl,
                TimeSpan.FromSeconds(options.RequestTimeoutSeconds),
                sp.GetRequiredService<ILoggerFactory>()));
            services.AddSingleton<IMovieSearchClient>(sp => new CachingMovieSearchClient(
                sp.GetRequiredService<McpMovieSearchClient>(),
                sp.GetRequiredService<Microsoft.Extensions.Caching.Memory.IMemoryCache>(),
                TimeSpan.FromSeconds(options.CacheTtlSeconds)));
        }

        return services;
    }

    public static IServiceCollection AddMovieSearchAuth(this IServiceCollection services, MovieSearchApiOptions options)
    {
        var signingKey = new SymmetricSecurityKey(Encoding.UTF8.GetBytes(options.JwtSigningKey));
        services.AddAuthentication(JwtBearerDefaults.AuthenticationScheme)
            .AddJwtBearer(jwt =>
            {
                jwt.MapInboundClaims = false;
                jwt.TokenValidationParameters = new TokenValidationParameters
                {
                    ValidateIssuer = true,
                    ValidIssuer = options.JwtIssuer,
                    ValidateAudience = true,
                    ValidAudience = options.JwtAudience,
                    ValidateIssuerSigningKey = true,
                    IssuerSigningKey = signingKey,
                    ValidateLifetime = true,
                    ClockSkew = TimeSpan.FromSeconds(30),
                    RoleClaimType = TokenService.RoleClaim,
                    NameClaimType = JwtRegisteredClaimNames.Sub,
                };
                jwt.Events = new JwtBearerEvents
                {
                    OnChallenge = context =>
                    {
                        context.HandleResponse();
                        context.Response.StatusCode = StatusCodes.Status401Unauthorized;
                        context.Response.ContentType = "application/problem+json";
                        return context.Response.WriteAsJsonAsync(new ProblemDetails
                        {
                            Status = StatusCodes.Status401Unauthorized,
                            Title = "Unauthorized",
                            Detail = "A valid Bearer token is required.",
                        });
                    },
                    OnForbidden = context =>
                    {
                        context.Response.StatusCode = StatusCodes.Status403Forbidden;
                        context.Response.ContentType = "application/problem+json";
                        return context.Response.WriteAsJsonAsync(new ProblemDetails
                        {
                            Status = StatusCodes.Status403Forbidden,
                            Title = "Forbidden",
                            Detail = "The token's role is not permitted for this endpoint. Reader may only call search.",
                        });
                    },
                };
            });
        services.AddAuthorization(auth =>
        {
            auth.AddPolicy(MovieEndpoints.ReaderOrAdmin, policy =>
                policy.RequireRole(TokenService.ReaderRole, TokenService.AdminRole));
            auth.AddPolicy(MovieEndpoints.AdminOnly, policy =>
                policy.RequireRole(TokenService.AdminRole));
        });
        return services;
    }

    public static IServiceCollection AddMovieSearchRateLimiting(
        this IServiceCollection services,
        MovieSearchApiOptions options)
    {
        services.AddRateLimiter(rate =>
        {
            rate.RejectionStatusCode = StatusCodes.Status429TooManyRequests;
            rate.OnRejected = async (context, token) =>
            {
                context.HttpContext.Response.StatusCode = StatusCodes.Status429TooManyRequests;
                context.HttpContext.Response.ContentType = "application/problem+json";
                await context.HttpContext.Response.WriteAsJsonAsync(
                    new ProblemDetails
                    {
                        Status = StatusCodes.Status429TooManyRequests,
                        Title = "Too Many Requests",
                        Detail = $"Rate limit of {options.RateLimitPerMinute} requests per minute exceeded.",
                    },
                    token).ConfigureAwait(false);
            };
            rate.AddPolicy("per-user", httpContext =>
            {
                var sub = httpContext.User.FindFirst(JwtRegisteredClaimNames.Sub)?.Value
                          ?? httpContext.User.Identity?.Name
                          ?? "anonymous";
                return RateLimitPartition.GetFixedWindowLimiter(sub, _ => new FixedWindowRateLimiterOptions
                {
                    PermitLimit = options.RateLimitPerMinute,
                    Window = TimeSpan.FromMinutes(1),
                    QueueLimit = 0,
                    AutoReplenishment = true,
                });
            });
        });
        return services;
    }

    public static IServiceCollection AddMovieSearchTelemetry(
        this IServiceCollection services,
        MovieSearchApiOptions options,
        IHostEnvironment environment)
    {
        var otel = services.AddOpenTelemetry()
            .ConfigureResource(resource => resource.AddService("movie-search-api"))
            .WithMetrics(metrics =>
            {
                metrics.AddAspNetCoreInstrumentation();
                metrics.AddHttpClientInstrumentation();
                metrics.AddRuntimeInstrumentation();
                metrics.AddMeter(McpTelemetry.MeterName);
                metrics.AddPrometheusExporter();
            })
            .WithTracing(tracing =>
            {
                tracing.AddAspNetCoreInstrumentation();
                tracing.AddHttpClientInstrumentation();
                tracing.AddSource(McpTelemetry.ActivitySourceName);
                if (!environment.IsEnvironment("Testing"))
                {
                    tracing.AddOtlpExporter(otlp =>
                    {
                        otlp.Endpoint = new Uri(options.OtlpEndpoint);
                    });
                }
            });
        _ = otel;
        return services;
    }
}
