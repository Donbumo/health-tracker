"""Web tests for recipe pages."""

from decimal import Decimal

from app.extensions import db
from app.models import FoodProduct, Recipe, User
from app.services.recipes import create_recipe_from_products
from tests.conftest import login


def _make_user(username: str) -> User:
    user = User(username=username, role="user")
    user.set_password("test-password")
    db.session.add(user)
    db.session.flush()
    return user


def _make_product(user_id: int, name: str = "Demo Product", **kwargs) -> FoodProduct:
    defaults = {
        "source": "manual",
        "calories_per_100g": Decimal("300.000"),
        "protein_g_per_100g": Decimal("20.000"),
        "fat_g_per_100g": Decimal("10.000"),
        "carbs_g_per_100g": Decimal("30.000"),
        "net_carbs_g_per_100g": Decimal("20.000"),
        "fiber_g_per_100g": Decimal("10.000"),
        "sodium_mg_per_100g": Decimal("100.000"),
    }
    defaults.update(kwargs)
    product = FoodProduct(user_id=user_id, name=name, **defaults)
    db.session.add(product)
    db.session.flush()
    return product


def test_recipes_list_requires_login(client):
    response = client.get("/recipes")
    assert response.status_code == 302
    assert "/login" in response.headers["Location"]


def test_recipes_empty_list_renders(client, app, user):
    with app.app_context():
        login(client)

    response = client.get("/recipes")
    assert response.status_code == 200
    assert "Recetas" in response.get_data(as_text=True)
    assert "No hay recetas todav" in response.get_data(as_text=True)


def test_new_recipe_requires_food_products(client, app, user):
    with app.app_context():
        login(client)

    response = client.get("/recipes/new")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Primero necesitas agregar productos" in body
    assert "/foods/new" in body


def test_create_recipe_from_web_and_show_detail(client, app, user):
    with app.app_context():
        product = _make_product(
            user,
            "Proteína XGear / Dr. Simi aislado",
            brand="XGear / Dr. Simi",
            calories_per_100g=Decimal("380.000"),
            protein_g_per_100g=Decimal("85.000"),
            fat_g_per_100g=Decimal("2.000"),
            carbs_g_per_100g=Decimal("0.000"),
            net_carbs_g_per_100g=Decimal("0.000"),
            fiber_g_per_100g=Decimal("0.000"),
            sodium_mg_per_100g=Decimal("100.000"),
        )
        db.session.commit()
        product_id = product.id
        login(client)

    response = client.post(
        "/recipes/new",
        data={
            "name": "Licuado web",
            "description": "Receta creada desde prueba web.",
            "servings": "2",
            "yield_weight_g": "400",
            "food_product_id[]": [str(product_id)],
            "quantity_g[]": ["40"],
            "ingredient_notes[]": ["Una porción."],
            "notes": "Notas de receta.",
        },
        follow_redirects=False,
    )

    assert response.status_code == 302
    assert "/recipes/" in response.headers["Location"]

    with app.app_context():
        recipe = db.session.execute(
            db.select(Recipe).where(
                Recipe.user_id == user,
                Recipe.name == "Licuado web",
            )
        ).scalar_one()
        assert len(recipe.ingredients) == 1
        assert recipe.ingredients[0].name_snapshot == "Proteína XGear / Dr. Simi aislado"
        assert recipe.ingredients[0].quantity_g == Decimal("40.000")

    detail = client.get(response.headers["Location"])
    assert detail.status_code == 200
    body = detail.get_data(as_text=True)
    assert "Licuado web" in body
    assert "Proteína XGear / Dr. Simi aislado" in body
    assert "Macros" in body
    assert "Ingredientes" in body


def test_recipe_detail_is_isolated_by_user(client, app, user):
    with app.app_context():
        other = _make_user("other-recipe-web-user")
        product = _make_product(other.id, "Other User Product")
        recipe = create_recipe_from_products(
            user_id=other.id,
            name="Other User Recipe",
            ingredients=[
                {
                    "food_product_id": product.id,
                    "quantity_g": Decimal("100.000"),
                }
            ],
        )
        recipe_id = recipe.id
        login(client)

    response = client.get(f"/recipes/{recipe_id}")
    assert response.status_code == 404


def test_recipes_list_shows_only_current_user_recipes(client, app, user):
    with app.app_context():
        own_product = _make_product(user, "Own Product")
        create_recipe_from_products(
            user_id=user,
            name="Own Recipe",
            ingredients=[
                {
                    "food_product_id": own_product.id,
                    "quantity_g": Decimal("100.000"),
                }
            ],
        )

        other = _make_user("other-recipe-list-user")
        other_product = _make_product(other.id, "Other Product")
        create_recipe_from_products(
            user_id=other.id,
            name="Other Recipe",
            ingredients=[
                {
                    "food_product_id": other_product.id,
                    "quantity_g": Decimal("100.000"),
                }
            ],
        )
        login(client)

    response = client.get("/recipes")
    assert response.status_code == 200
    body = response.get_data(as_text=True)
    assert "Own Recipe" in body
    assert "Other Recipe" not in body