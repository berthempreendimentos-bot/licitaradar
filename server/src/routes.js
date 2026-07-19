const { Router } = require("express");
const {
  listar,
  buscarPorId,
  criar,
  atualizar,
  excluir,
} = require("./controllers/contratacaoController");

const routes = Router();

routes.get("/contratacoes", listar);
routes.get("/contratacoes/:id", buscarPorId);
routes.post("/contratacoes", criar);
routes.put("/contratacoes/:id", atualizar);
routes.delete("/contratacoes/:id", excluir);

module.exports = routes;
