const { PrismaClient } = require("@prisma/client");
const { PrismaBetterSqlite3 } = require("@prisma/adapter-better-sqlite3");

const adapter = new PrismaBetterSqlite3({ url: process.env.DATABASE_URL });
const prisma = new PrismaClient({ adapter });

const listar = async (req, res) => {
  try {
    const contratacoes = await prisma.contratacao.findMany({
      orderBy: { criadoEm: "desc" },
    });
    res.json(contratacoes);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
};

const buscarPorId = async (req, res) => {
  try {
    const { id } = req.params;
    const contratacao = await prisma.contratacao.findUnique({
      where: { id },
    });
    if (!contratacao) {
      return res.status(404).json({ error: "Contratacao nao encontrada" });
    }
    res.json(contratacao);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
};

const criar = async (req, res) => {
  try {
    const {
      codigoContabilidade,
      processo,
      nup,
      tipoCompra,
      modalidade,
      criterioJulgamento,
      situacaoControle,
      unidadeCompradora,
      objetoCompra,
    } = req.body;

    const contratacao = await prisma.contratacao.create({
      data: {
        codigoContabilidade,
        processo,
        nup,
        tipoCompra,
        modalidade,
        criterioJulgamento,
        situacaoControle,
        unidadeCompradora,
        objetoCompra,
      },
    });
    res.status(201).json(contratacao);
  } catch (error) {
    res.status(500).json({ error: error.message });
  }
};

const atualizar = async (req, res) => {
  try {
    const { id } = req.params;
    const {
      codigoContabilidade,
      processo,
      nup,
      tipoCompra,
      modalidade,
      criterioJulgamento,
      situacaoControle,
      unidadeCompradora,
      objetoCompra,
    } = req.body;

    const contratacao = await prisma.contratacao.update({
      where: { id },
      data: {
        codigoContabilidade,
        processo,
        nup,
        tipoCompra,
        modalidade,
        criterioJulgamento,
        situacaoControle,
        unidadeCompradora,
        objetoCompra,
      },
    });
    res.json(contratacao);
  } catch (error) {
    if (error.code === "P2025") {
      return res.status(404).json({ error: "Contratacao nao encontrada" });
    }
    res.status(500).json({ error: error.message });
  }
};

const excluir = async (req, res) => {
  try {
    const { id } = req.params;
    await prisma.contratacao.delete({
      where: { id },
    });
    res.status(204).send();
  } catch (error) {
    if (error.code === "P2025") {
      return res.status(404).json({ error: "Contratacao nao encontrada" });
    }
    res.status(500).json({ error: error.message });
  }
};

module.exports = { listar, buscarPorId, criar, atualizar, excluir };
