/* Entirely fictional QA data. No imported food dataset, real user or health advice. */
(() => {
  const definitions = [
    ['energy','Energía','kcal','Macros'],['protein','Proteína','g','Macros'],
    ['carbohydrate','Carbohidratos totales','g','Macros'],['fat','Grasa','g','Macros'],['fiber','Fibra','g','Macros'],
    ['sodium','Sodio','mg','Minerales'],['potassium','Potasio','mg','Minerales'],['calcium','Calcio','mg','Minerales'],
    ['iron','Hierro','mg','Minerales'],['magnesium','Magnesio','mg','Minerales'],['phosphorus','Fósforo','mg','Minerales'],['zinc','Zinc','mg','Minerales'],
    ['vitamin_a','Vitamina A (RAE)','µg','Vitaminas'],['vitamin_c','Vitamina C','mg','Vitaminas'],['vitamin_d','Vitamina D','µg','Vitaminas'],
    ['vitamin_e','Vitamina E','mg','Vitaminas'],['vitamin_k','Vitamina K','µg','Vitaminas'],['thiamin','Tiamina','mg','Vitaminas'],
    ['riboflavin','Riboflavina','mg','Vitaminas'],['niacin','Niacina','mg','Vitaminas'],['vitamin_b6','Vitamina B6','mg','Vitaminas'],
    ['folate','Folato (DFE)','µg','Vitaminas'],['vitamin_b12','Vitamina B12','µg','Vitaminas'],['choline','Colina','mg','Otros']
  ].map(([id,label,unit,group]) => ({id,label,unit,group}));
  const food = (id,name,kind,nutrients,servings = []) => ({id,name,kind,base:100,unit:'g',revision:'qa-1',
    provenance:{source:kind==='user'?'user':'qa_catalog',source_food_id:id,source_revision:'qa-2026-10',source_name:kind==='user'?'Creado por ti · DEMO':'Catálogo ficticio QA',nutrient_revision:'qa-1',verified_at:null},nutrients,servings});
  const foods = [
    food('chicken','Pechuga de pollo, cocida','catalog',{energy:165,protein:31,carbohydrate:0,fat:3.6,fiber:0,sodium:74,potassium:250,calcium:12,iron:1,magnesium:29,phosphorus:220,zinc:1,vitamin_c:0,vitamin_d:null,vitamin_k:null,choline:80}),
    food('raw','Pechuga de pollo, cruda','catalog',{energy:120,protein:23,carbohydrate:0,fat:2.5,fiber:0,sodium:45,iron:0.7}),
    food('rice','Arroz blanco, cocido','catalog',{energy:130,protein:2.7,carbohydrate:28,fat:0.3,fiber:0.4,sodium:1,potassium:35,calcium:10,iron:1.2,magnesium:12,phosphorus:40,zinc:0.5,vitamin_c:0,vitamin_d:0},[{id:'cup',label:'Taza QA',grams:158}]),
    food('avocado','Aguacate','catalog',{energy:160,protein:2,carbohydrate:8.5,fat:14.7,fiber:6.7,sodium:7,potassium:480,calcium:12,iron:0.6,magnesium:29,phosphorus:50,zinc:0.6,vitamin_c:10,vitamin_d:0,vitamin_k:21,folate:80},[{id:'half',label:'Media pieza QA',grams:75}]),
    food('salsa','Salsa de casa','user',{energy:35,protein:1,carbohydrate:7,fat:0.2,fiber:null,sodium:350}),
    food('yogurt','Yogurt natural · Marca Demo','user',{energy:90,protein:8,carbohydrate:9,fat:2.5,fiber:0,sodium:45,calcium:140,vitamin_d:1},[{id:'pot',label:'Envase QA',grams:150}])
  ];
  const bowl = {name:'Bowl de pollo + arroz',type:'Comida',ingredients:[{foodId:'chicken',amount:180,unit:'g'},{foodId:'rice',amount:200,unit:'g'},{foodId:'avocado',amount:60,unit:'g'},{foodId:'salsa',amount:30,unit:'g'}]};
  // These values only exercise reference UI; they are NOT dietary recommendations.
  window.NutritionQA = {definitions,foods,bowl,goals:{protein:180,carbohydrate:240,fat:75,fiber:30},
    references:{calcium:120,iron:6,magnesium:150,vitamin_c:5},
    initial:[{name:'Yogurt natural',type:'Desayuno',ingredients:[{foodId:'yogurt',amount:150,unit:'g'}]},bowl]};
})();
