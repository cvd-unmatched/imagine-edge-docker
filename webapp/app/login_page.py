def render_login_page(error: bool = False) -> str:
    error_block = (
        '<p class="login-form__error" role="alert">Wrong username or password. Try again.</p>'
        if error
        else ""
    )
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
	<meta charset="UTF-8">
	<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
	<title>Camera Sync: Sign in</title>
	<link rel="stylesheet" href="/style.css">
</head>
<body class="login-body">
	<main class="login-card">
		<span class="brand">
			<span class="brand__mark" aria-hidden="true">S<span class="brand__lens"></span>NY</span>
			<span class="brand__sub">Imagine Edge Docker</span>
		</span>
		<form class="login-form" method="post" action="/login">
			<label class="login-form__label" for="username">Username</label>
			<input class="login-form__input" type="text" id="username" name="username" autocomplete="username" required autofocus>
			<label class="login-form__label" for="password">Password</label>
			<input class="login-form__input" type="password" id="password" name="password" autocomplete="current-password" required>
			{error_block}
			<button class="login-form__submit" type="submit">Sign in</button>
		</form>
	</main>
</body>
</html>
"""
